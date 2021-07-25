#! /usr/bin/env python3


from __future__ import annotations
from dataclasses import dataclass, field
import pickle
import random
import math

import matplotlib.pyplot as plt


@dataclass
class MeasuredGossipPropagationDelayModel(object):
    samples: list

    @classmethod
    def load(cls, filename, node=0):
        all_samples = pickle.load(open(filename, "rb"))
        return cls(all_samples[sorted(all_samples.keys())[node]])

    def sample(self, rng):
        return MeasuredGossipPropagationDelayModelInstance(rng.choice(self.samples))


@dataclass
class MeasuredGossipPropagationDelayModelInstance(object):
    samples: list

    def sample(self, rng, k):
        return rng.sample(self.samples, k)


def simulate_vote_after_propagation_and_intercept(rng, gossip_propagation_samples, n_honest, adversaries, i_adversary_alert, T_adversary_delay):
    # sample a random location for the block proposer and a corresponding block propagation delay distribution
    proposer = rng.choice(range(len(gossip_propagation_samples)))
    proposer_msg_dist = gossip_propagation_samples[proposer].sample(rng)

    # sample the delay from block proposer to adversarial nodes
    # and determine when adversaries begin broadcasting the sway vote
    T_adv = sorted(proposer_msg_dist.sample(rng, len(adversaries)))[i_adversary_alert]

    # sample propagation delay distribution for each adversarial node (given its location)
    adv_msg_dist = [ gossip_propagation_samples[adv].sample(rng) for adv in adversaries ]

    # for each honest committee member ...
    hons = []
    for j in range(n_honest):
        # ... sample the delay of block proposal
        T_proposal = proposer_msg_dist.sample(rng, 1)[0]
        # ... sample the delay of sway vote
        T_advs = [ dist.sample(rng, 1)[0] + T_adv + T_adversary_delay for (i, dist) in enumerate(adv_msg_dist) ]

        # ... depending on whether block proposal or sway vote arrive first ...
        if T_proposal < min(T_advs):
            hons.append(0) # ... vote with tie break
        else:
            hons.append(1) # ... vote with sway

    return hons


# load gossip network propagation samples (uncompress provided pickle file first!)
gossip_propagation_samples = [ MeasuredGossipPropagationDelayModel.load("samples_simplified_afcf8c74bc552b0506a3a1c58f74c2ac.pickle", node=i) for i in range(5) ]

# reproducibility
rng = random.Random(2342)

# scenario
n_committee_honest = 120   # number of honest committee members (ignoring random draw)
adversaries = [2,]*25   # number of adversarial nodes in the network and their "position" (propagation delay CDF)
i_adversary_alert = 4   # adversary releases sway vote when i_adversary_alert adversarial nodes have received this slot's proposal
T_delay = 0.0   # delay between when i_adversary_alert adversarial nodes have received this slot's proposal and release of sway vote


# Monte Carlo experiments
results = []
for i in range(10000):
    hons = simulate_vote_after_propagation_and_intercept(rng, gossip_propagation_samples, n_committee_honest, adversaries, i_adversary_alert, T_delay)
    results.append(sum(hons)/len(hons))


def mean(lst):
    return sum(lst)/len(lst)

def variance(lst):
    m = mean(lst)
    return mean([ (l-m)**2 for l in lst ])

def stddev(lst):
    return math.sqrt(variance(lst))

print(results)   # fraction of honest validators voting with sway per experiment
print(mean(results), variance(results), stddev(results), math.sqrt(mean(results) * (1-mean(results))))   # stats


# plot histogram
plt.figure()
p = plt.hist(results)
plt.xlim(0, 1)
plt.savefig(f"eth2-attack-unknown-proposal-time-adv{len(adversaries)}-i{i_adversary_alert}-T{T_delay}.png")

# raw data of the histogram
print(p[0])
print(p[1])
