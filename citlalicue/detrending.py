import numpy as np
import matplotlib.pyplot as plt
from numpy.random import multivariate_normal
from scipy.spatial.distance import cdist
from scipy.interpolate import interp1d

from citlalicue.citlalicue import light_curve
#import QuadraticModel from pytransit
from pytransit import QuadraticModel


class detrend():
    """
    Ths class detrends light curves using GPs
    """

    def __init__(self,fname,bin=10,err=0):
        """Load the light curve to be detrended
        The bin variables are used to speed up computation of the GP
        """

        self.fname = fname

        if err == 0:
            self.time, self.flux, self.ferr = np.loadtxt(fname,unpack=True)
        else:
            self.time, self.flux = np.loadtxt(fname,unpack=True)
            self.ferr = np.array([err]*len(self.time))

        self.time_bin = self.time[::bin]
        self.flux_bin = self.flux[::bin]
        self.ferr_bin = self.ferr[::bin]

        #Initialise the planet-related fluxes
        self.nplanets = 1
        self.flux_planet = np.ones(len(self.time))
        self.flux_planet_bin = np.ones(len(self.time_bin))
        self.flux_no_planet = self.flux
        self.flux_no_planet_bin = self.flux_bin

    def add_transits(self,pars,ldc):
        """
        Add transits, so they can be removed from the detrending routines
        pars -> [T0, P, a/R*, inclination, Rp/R*] x Number of planets
        ldc  -> u1, u2
        """

        #Add parameters to the class
        self.planet_pars = pars
        self.ldc = ldc

        #number of planets to be added
        npl = int(len(pars)/5)
        self.nplanets = npl
        #We compute the model with
        tm = QuadraticModel()
        tm.set_data(self.time)
        tm_bin = QuadraticModel()
        tm_bin.set_data(self.time_bin)
        flux = 1
        flux_bin = 1
        for i in range(npl):
            flux     = flux     * tm.evaluate(t0=pars[0+5*i], p=pars[1+5*i], a=pars[2+5*i], i=pars[3+5*i],k=pars[4+5*i], ldc=ldc)
            flux_bin = flux_bin * tm_bin.evaluate(t0=pars[0+5*i], p=pars[1+5*i], a=pars[2+5*i], i=pars[3+5*i],k=pars[4+5*i], ldc=ldc)

        self.flux_planet = flux
        self.flux_planet_bin = flux_bin
        self.flux_no_planet = self.flux / flux
        self.flux_no_planet_bin = self.flux_bin / flux_bin


    def get_gp(self,Kernel="Exp"):
        import george
        from george import kernels
        if Kernel == "Matern32":
            kernel = 0.1 * kernels.Matern32Kernel(10.)
        elif Kernel == "Matern52":
            kernel = 0.1*kernels.Matern52Kernel(10.)
        elif Kernel == "Exp":
            kernel = 0.1*kernels.ExpKernel(10.)

        self.kernel = kernel
        #Compute the kernel with George
        self.gp = george.GP(self.kernel,mean=1)
        #We compute the kernel using the binned data
        self.gp.compute(self.time_bin, self.ferr_bin)

    def draw_sample(self):
        sample_flux = self.gp.sample(self.time_bin)
        plt.plot(self.time_bin,sample_flux)
        plt.show()

    def predict(self):
        pred, pred_var = self.gp.predict(self.flux_no_planet_bin, self.time_bin, return_var=True)
        plt.figure(figsize=(15,5))
        plt.plot(self.time_bin,self.flux_bin,'ko',alpha=0.25)
        plt.plot(self.time_bin,pred,'r')
        plt.show()


    #p has to be a vector that contains the planet parameters + the hyper parameters
    #def neg_ln_like(p,t,f,npl):
    def neg_ln_like(self,p):
      #The first 5*npl elements will be planet parameters
     #The 5*npl + 1 and + 2 will be LDC
     #The last elements will be hyperparameters
        #    f_local = f - transits(t,p[0:5*npl],p[5*npl:5*npl+2],npl)
        self.gp.set_parameter_vector(p)
        return -self.gp.log_likelihood(self.flux_no_planet_bin)

    #p has to be a vector that contains the planet parameters + the hyper parameters
    #def grad_neg_ln_like(p,t,f,npl):
    #def grad_neg_ln_like(p):
        #The first 5*npl elements will be planet parameters
        #The 5*npl + 1 and + 2 will be LDC
        #The last elements will be hyperparameters
    #    f_local = f - transits(t,p[0:5*npl],p[5*npl:5*npl+2],npl)
    #    self.gp.set_parameter_vector(p)
    #    return -self.gp.grad_log_likelihood(self.flux_no_planet_bin)

    def optimize(self):
        from scipy.optimize import minimize
        self.result = minimize(self.neg_ln_like,self.gp.get_parameter_vector())

    def detrend(self):
        """detrend the original data set"""
        #Take the values from the optimisation
        self.gp.set_parameter_vector(self.result.x)
        #Recompute the correlation matrix
        self.gp.compute(self.time,self.ferr)
        #Predict the model for the original data set
        self.pred, self.pred_var = self.gp.predict(self.flux_no_planet, self.time, return_var=True)
        #Compute the detrended flux
        self.flux_detrended = self.flux / self.pred

        vectorsote = np.array([self.time,self.flux_detrended,self.ferr,self.flux,self.pred,self.flux_planet])
        header = "Time  Detrended_flux  flux_error  flux  GP_model  planets_model"
        fname = self.fname[:-4]+'_detrended.dat'
        print("Saving {} file".format(fname))
        np.savetxt(fname,vectorsote.T,header=header)

    def cut_transits(self,durations=6./24.):

        #Extract the ephemeris from the planet_pars attribute
        if hasattr(self,'planet_pars'):
            T0 = self.planet_pars[0::5]
            P  = self.planet_pars[1::5]
        else:
            print("There are no planet parameters in the current class")


        if durations.__class__ != list:
            durations = [durations]*self.nplanets
        else:
            if len(durations) != self.nplanets:
                durations = [max(durations)]*self.nplanets

        #Create a list of lists to find the regions where the transits are for each planet
        tr = [None]*self.nplanets

        for o in range(0,self.nplanets):
            phase = ((self.time-T0[o])%P[o])/P[o]
            phase[phase>0.5] -= 1
            tr[o] = abs(phase) <= (2*durations[o])/P[o]

        #Let us combine all the data with a logical or
        indices = tr[0]
        if self.nplanets > 1:
            for o in range(1,self.nplanets):
                indices = np.logical_or(indices,tr[o])

        #Now indices contains all the elements where there are transits
        #Let us extract them
        self.time_cut = self.time[indices]
        self.flux_cut = self.flux[indices]
        self.ferr_cut = self.ferr[indices]

        vectorsote = np.array([self.time_cut,self.flux_cut,self.ferr_cut])
        fname = self.fname[:-4]+'_cut.dat'
        if hasattr(self,"flux_detrended"):
            self.flux_detrended_cut = self.flux_detrended[indices]
            vectorsote = np.array([self.time_cut,self.flux_detrended_cut,self.ferr_cut])
            fname = self.fname[:-4]+'_detrended_cut.dat'

        print("Saving {} file".format(fname))
        np.savetxt(fname,vectorsote.T)


    def plot(self,fsx=15,fsy=5,fname='light_curve.pdf',save=False,show=True,xlim=[None]):
        plt.figure(figsize=(fsx,fsy))
        plt.xlabel('Time [days]')
        plt.ylabel('Normalised flux')
        plt.plot(self.time,self.flux,'.',color="#bcbcbc",alpha=0.5,label='LC data')
        if hasattr(self,'pred'):
            plt.plot(self.time,self.pred*self.flux_planet,'-',color="#b30000",label='Model')
        if hasattr(self,'flux_detrended'):
            plt.plot(self.time,self.flux_detrended-6*np.std(self.flux),'.',color="#005ab3",alpha=0.5,label='LC detrended')
            plt.plot(self.time,self.flux_planet-6*np.std(self.flux),'#ff7f00',label='Flat LC model')
            plt.ylabel('Normalised flux + offset')
        plt.legend(loc=1,ncol=5,scatterpoints=1,numpoints=1,frameon=True)
        plt.xlim(self.time.min(),self.time.max())
        try:
            plt.xlim(*xlim)
        except:
            pass
        if save:
            plt.savefig(fname,bbox_inches='tight',rasterized=True)
        if show:
            plt.show()
        plt.close()