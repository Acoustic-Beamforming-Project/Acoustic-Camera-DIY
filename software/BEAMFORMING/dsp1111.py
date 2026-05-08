import numpy as np
# import cupy as cp
import scipy as sp
from scipy.fft import fft, fftfreq, fftshift , ifft , ifftshift
import matplotlib as plt

c = 34300

class signal: 
    def __init__(self, signal : np.array, time : np.array, Num_samples , sampling_rate, Array, direction_X):
        self.sampling_period = 1/sampling_rate
        self.values = signal 
        self.time = time
        self.freqs = fftshift(fftfreq(Num_samples,self.sampling_period))
        self.fft = fftshift(fft(signal))
        self.dalayed_signal = self.fft * Array.give_signal_direction(self.freq, direction_X)

class Array :

    test_vec = np.exp(-1j*(2*np.pi) * np.linspace(0,180,200))

    def __init__(self , size:int , spacing):
        self.size = size
        self.spacing = spacing
        self.weights = self.get_weights()
        self.beam_pattern = self.get_beam_pattern()
        
# return the replica vector
    def give_signal_direction(self,freq,direction_x):
        delays = np.ones(self.size)
        replica_vector = np.exp(-1j*(2*np.pi*freq) * delays)
        return replica_vector
    

# return array weights for direction range
    def get_weights(self, freq = 4000, start_theta = 30 , stop_theta=120, step_theta=5):  
        return np.exp(1j * freq * (np.arange(start_theta, stop_theta, step_theta)) ) 
    
# return an array of the beampattern and angles --> plot on radian graph 
    def get_beam_pattern(self):
        return np.np.matmul(self.weights , self.test_vec)

# return the array response for a given signal 
    def get_array_response(self, signal: signal):
        return np.np.matmul (self.weights , signal.dalayed_signal)


Array = Array(15,3)









# import numpy as np
# # import cupy as cp
# import scipy as sp
# import matplotlib as plt


# class signal: 
#     def __init__(self, freq , sample_rate, Array, direction_X, direction_Y):
#         self.freq = freq
#         self.sample_rate = sample_rate
#         self.time = np.linspace(0,0.1,1000)
#         self.value = np.sin(2 * freq * np.pi * self.time)
#         self.fft = np.fft(self.value , self.time)
#         self.dalayed_signal = self.fft * Array.give_signal_direction(self.freq, direction_X , direction_Y)

# class Array :

#     test_vec = np.exp(-1j*(2*np.pi) * np.linspace(0,180,200))

#     def __init__(self , size:int , spacing):
#         self.size = size
#         self.spacing = spacing
#         self.weights = self.get_weights()
#         self.beam_pattern = self.get_beam_pattern()
        
# # return the replica vector
#     def give_signal_direction(self,freq,direction_x, direction_y):
#         delays = np.ones(self.size)
#         replica_vector = np.exp(-1j*(2*np.pi*freq) * delays)
#         return replica_vector
    

# # return array weights for direction range
#     def get_weights(self, freq, start_theta , stop_theta, step_theta , start_phi , stop_phi, step_phi):
#         weights_x = np.linspace(start_theta, stop_theta, step_theta)  
#         weights_y = np.linspace(start_phi, stop_phi, step_phi)  
#         weights = np.exp(1j * freq * (weights_x + weights_y) )
#         return weights 
    
# # return an array of the beampattern and angles --> plot on radian graph 
#     def get_beam_pattern(self):
#         return np.dot (self.weights , self.test_vec)

# # return the array response for a given signal 
#     def get_array_response(self, signal: signal):
#         return np.dot (self.weights , signal.dalayed_signal)


# Array = Array(15,3)