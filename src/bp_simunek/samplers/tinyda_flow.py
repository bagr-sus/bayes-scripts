from pathlib import Path
import os
import time
import shutil
import tinyDA as tda
import scipy.stats as sps
import numpy as np
import logging
import arviz as az
import ray
from ray.util.actor_pool import ActorPool

from bp_simunek.simulation.measured_data import MeasuredData
from bp_simunek.simulation.flow_wrapper import RemoteWrapper

@ray.remote
class PoolWrapper():
    def init_pool(self, pool):
        self.pool = pool

    def has_idle(self):
        return self.pool.has_free()

    def get_idle(self):
        return self.pool.pop_idle()

    def push_idle(self, flow):
        return self.pool.push(flow)


class TinyDAFlowWrapper():
    """
    Wrapper combining a flow123 instance into a tinyDA sampler
    """

    def __init__(self, flow_wrapper, chains):
        self.flow_wrapper = flow_wrapper
        self.observed_data = MeasuredData(self.flow_wrapper.sim._config)
        self.observed_data.initialize()
        self.noise_dist = sps.norm(loc = 0, scale = 2e-4)
        self.chains = chains
        self.worker_dirs = []
        if self.chains > 1:
            self.setup_flow_pool(threadcount=chains)
            self.parallel = True
        else:
            self.parallel = False

    def create_workdirs(self, basedir, dirnames, datadir):
        """
        Clean or create workdirs for worker threads.
        :param basedir
        """
        logging.info("Creating worker directories...")
        abs_dirnames = [Path(os.path.join(basedir, dirname)).absolute() for dirname in dirnames]
        print(basedir)
        if os.path.exists(basedir):
            shutil.rmtree(basedir)
            
        for dir in abs_dirnames:
            os.makedirs(dir, mode=0o755)
            shutil.copytree(datadir, dir, ignore=shutil.ignore_patterns("worker"), dirs_exist_ok=True)
            logging.info(f"{dir} created")
            self.worker_dirs.append(dir)
        # TODO check if dirs are created succesfully
        logging.info("Creating worker directories DONE")


    def setup_flow_pool(self, threadcount = 4):
        logging.info("Setting up flow pool...")
        # attempt to alleviate error - expand pool
        #threadcount *= 2
        dirnames = [f"worker{i}" for i in range(threadcount)]
        # create worker directories
        workdir = self.flow_wrapper.sim._config["work_dir"]
        basedir = os.path.join(workdir, "worker")
        self.create_workdirs(basedir, dirnames, workdir)
        # create flow wrappers
        logging.info("Creating wrappers...")
        pool = [RemoteWrapper.remote() for _ in range(threadcount)]
        jobs = []
        logging.info("Initializing wrappers...")
        for idx, wrapper in enumerate(pool):
            jobs.append(wrapper.initialize.remote(idx, self.worker_dirs[idx]))
        while jobs:
            _, jobs = ray.wait(jobs)

        logging.info("Adding observe paths...")
        for wrapper in pool:
            jobs.append(wrapper.set_observe_path.remote(self.flow_wrapper.sim._config["measured_data_dir"]))
        while jobs:
            _, jobs = ray.wait(jobs)

        logging.info("Creating pool thread...")
        #self.pool = ActorPool(pool)
        pool = ActorPool(pool)
        pool_wrapper = PoolWrapper.remote()
        job = pool_wrapper.init_pool.remote(pool)
        while job:
            _, job = ray.wait([job])
        self.pool = pool_wrapper
        logging.info("Setting up flow pool DONE")



    def sample(self, sample_count = 20, tune = 1) -> az.InferenceData:

        # setup priors from config of flow wrapper
        self.setup_priors(self.flow_wrapper.sim._config)

        # setup likelihood
        md = MeasuredData(self.flow_wrapper.sim._config)
        md.initialize()
        boreholes = ["H1"]
        cond_boreholes = []
        _, values = md.generate_measured_samples(boreholes, cond_boreholes)
        self.setup_loglike(values, np.eye(len(values)))

        # combine into posterior
        posterior = tda.Posterior(self.prior, self.loglike, self.forward_model)

        # setup proposal
        proposal = tda.IndependenceSampler(self.prior)

        # sampling process
        samples = tda.sample(posterior, proposal, iterations=sample_count, n_chains=self.chains)

        # check and save samples
        idata = tda.to_inference_data(chain=samples, parameter_names=self.prior_names, burnin=tune)

        return idata

    def setup_priors(self, config):
        priors = []
        prior_names = []
        for param in config["parameters"]:
            prior_name = param["name"]
            bounds = param["bounds"]
            match param["type"]:
                case "lognorm":
                    prior = sps.lognorm(s = bounds[1], scale = np.exp(bounds[0]))
                case "unif":
                    prior = sps.uniform(loc = bounds[0], scale = bounds[1] - bounds[0])
                case "truncnorm":
                    # https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.truncnorm.html
                    a_trunc, b_trunc, mu, sigma = bounds
                    a, b = (a_trunc - mu) / sigma, (b_trunc - mu) / sigma
                    prior = sps.truncnorm(a, b, loc=mu, scale=sigma)
            priors.append(prior)
            prior_names.append(prior_name)

        self.priors = priors
        self.prior_names = prior_names
        self.prior = tda.CompositePrior(priors)

    def setup_loglike(self, observed, cov):
        self.loglike = tda.GaussianLogLike(observed, cov)

    def forward_model(self, params):
        # if parallel sampling
        if self.parallel:
            # get idle flow solver
            # TODO figure out why threads get stuck and no new idle threads show up
            # when using self.pool.push(flow) - only 1 thread will run at a time
            # when not using it - multiple threads, but no idle threads left
            # reorder threads in pool?
            # a blocking in some thread?
            while True:
                if self.pool.has_idle.remote():
                    job = self.pool.get_idle.remote()
                    ndone = job
                    while ndone:
                        _, ndone = ray.wait([ndone])
                    flow = ray.get(job)
                    break
                time.sleep(2)
            # create new thread to pass params to it
            job = flow.set_parameters.remote(data_par=params)
            # wait to set params
            while job:
                _, job = ray.wait([job])
            # await observations
            job = flow.get_observations.remote()
            ndone = job
            while ndone:
                _, ndone = ray.wait([ndone])
            res, data = ray.get(job)

            self.pool.push_idle.remote(flow)

            if self.flow_wrapper.sim._config["conductivity_observe_points"]:
                num = len(self.flow_wrapper.sim._config["conductivity_observe_points"])
                data = data[:-num]
            if res >= 0:
                return data
        else:
            self.flow_wrapper.set_parameters(data_par=params)
            res, data = self.flow_wrapper.get_observations()
            if self.flow_wrapper.sim._config["conductivity_observe_points"]:
                num = len(self.flow_wrapper.sim._config["conductivity_observe_points"])
                data = data[:-num]
            if res >= 0:
                return data
