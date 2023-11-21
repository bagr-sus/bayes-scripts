from math import pi
import numpy as np
import numpy.random as npr
from scipy.stats import multivariate_normal
import arviz as az

generator = npr.Generator(npr.MT19937())

# Simple metropolis implementation for one variable
def norm_pdf(value, mean, std):
    return 1 / (std * np.sqrt(2 * pi)) * np.exp(-1 / 2 * np.power((value - mean) / std, 2))

def mvn_pdf(rnd, mean, cov):
    return multivariate_normal.pdf(rnd, mean, cov)

def sample_prior(samples=10000, mean=np.array([5,3]), cov=np.array([[4,-2],[-2,4]])):
    values = generator.multivariate_normal(mean=mean, cov=cov, size=samples, check_valid='warn')
    #adj_cov = np.multiply(2 * np.pi, cov)
    #factor = np.sqrt(np.linalg.det(adj_cov))

    likelihoods = np.array(multivariate_normal(mean=mean, cov=cov).pdf(values))
    #likelyhoods = np.divide(likelihoods, factor)
    return values, likelihoods

def metropolis(
        samples=10000,
        tune=3000,
        prior_mean=np.array([5,3]),
        prior_sigma=np.array([[4, -2], [-2, 4]])):
    # set up result array
    total_samples = samples + tune
    sampled = {"U": np.zeros((total_samples, 2)), "G": np.zeros(total_samples)}
    likelihood = np.zeros(total_samples)
    # prior
    prior_pdf = lambda rnd: mvn_pdf(rnd, prior_mean, prior_sigma)
    prior_candidate = lambda mean: generator.multivariate_normal([mean[0], mean[1]], prior_sigma)
    # posterior
    posterior_std = 2e-4
    posterior_operator = lambda u: -1 / 80 * (3 / np.exp(u[0]) + 1 / np.exp(u[1]))
    observed_value = -1e-3
    posterior_pdf = lambda rnd: norm_pdf(rnd - observed_value, 0, posterior_std)

    # sampling process
    accepted = 0
    g = 0
    u = prior_mean
    while accepted < total_samples:
        # get U candidate sample
        u_candidate = prior_candidate(u)
        g_candidate = posterior_operator(u_candidate)

        # accept/reject candidates
        u_current_probability = prior_pdf(u)
        u_candidate_probability = prior_pdf(u_candidate)

        g_candidate_probability = posterior_pdf(g_candidate)
        g_current_probability = posterior_pdf(g)
        threshold = min([1, g_candidate_probability / g_current_probability * u_candidate_probability / u_current_probability])

        random_probability = npr.uniform()

        if random_probability < threshold:
            sampled["U"][iteration] = u_candidate
            sampled["G"][iteration] = g_candidate
            likelihood[iteration] = np.log(g_candidate_probability * u_candidate_probability)
            u = u_candidate
            g = g_candidate
        else:
            sampled["U"][iteration] = u
            sampled["G"][iteration] = g
            likelihood[iteration] = np.log(g_current_probability * u_current_probability)

    # remove burn in from samples
    sampled["U"] = sampled["U"][tune:]
    sampled["G"] = sampled["G"][tune:]
    likelihood = likelihood[tune:]

    # reshape data to match pymc
    sampled["U"] = sampled["U"].reshape((1, -1, 2))
    sampled["G"] = sampled["G"].reshape((1, -1))

    # construct idata from sampled data
    idata = az.convert_to_inference_data({
        "U": sampled["U"],
        "G_mean": sampled["G"]
        })
    # add likelyhood data to main idata
    likelihood_idata = az.convert_to_inference_data({
        "G": likelihood
    }, group="log_likelihood")
    idata.extend(likelihood_idata)

    # add prior data
    prior_samples, prior_likelihood = sample_prior(samples)
    prior_samples = prior_samples.reshape(1, -1, 2)
    prior_likelihood = prior_likelihood.reshape(1, -1)
    prior_idata = az.convert_to_inference_data({
        "U": prior_samples,
        "likelihood": prior_likelihood
    }, group="prior")
    idata.extend(prior_idata)

    return idata


if __name__ == "__main__":
    idata = metropolis(samples=10000)
    print(idata)
    print(idata["posterior"])
    print(idata["log_likelihood"])
    print(idata["prior"])
    print()
 