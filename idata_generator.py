import numpy as np
from pymc_metropolis import generate_idata_sets
# idata is saved to folder /idata relative to this script's directory
# all heavy lifting is done by the generate_idata_sets method
# 

def generate_standard_data_sets():
    samples = 10000
    tune = 20000
    prior_mean = np.array([5, 3])
    prior_cov = np.array([[4, -2],[-2, 4]])
    prefix = "standard"
    print("--------------------------------")
    print("Generating standard data sets...")
    print("--------------------------------")
    print("\n")
    generate_idata_sets(samples=samples, tune=tune, prior_mean=prior_mean, prior_cov=prior_cov, prefix=prefix)

def generate_offset_data_sets():
    samples = 10000
    tune = 20000
    prior_mean = np.array([7, 4.2])
    prior_cov = np.array([[10, -5],[-5, 10]])
    prefix = "offset"
    print("--------------------------------")
    print("Generating offset data sets...")
    print("--------------------------------")
    print("\n")
    generate_idata_sets(samples=samples, tune=tune, prior_mean=prior_mean, prior_cov=prior_cov, prefix=prefix)




if __name__ == "__main__":
    generate_standard_data_sets()
    generate_offset_data_sets()
