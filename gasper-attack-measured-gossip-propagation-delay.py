#! /usr/bin/env python3.8


from __future__ import annotations
from dataclasses import dataclass, field
import random
import copy
import pickle


@dataclass
class Scenario(object):
    C: int   # number of slots per epoch
    N: int   # number of validators
    F: int   # number of adversarial validators

    def __post_init__(self):
        assert (self.N % self.C) == 0

    def slot_to_epoch(self, slot):
        return (slot // self.C, slot % self.C)

    def committee_size(self):
        return self.N // self.C

    def is_adversarial(self, i):
        return i < self.F

    def is_honest(self, i):
        return not self.is_adversarial(i)

    def all_parties(self):
        return range(self.N)


@dataclass
class RandomSchedule(object):
    scenario: Scenario
    randomness: int

    def committee_for_slot(self, slot):
        (epoch, slot_within_block) = self.scenario.slot_to_epoch(slot)
        committee_size = self.scenario.committee_size()

        rng = random.Random(self.randomness + epoch)
        committees = list(self.scenario.all_parties())
        rng.shuffle(committees)

        return committees[(slot_within_block*committee_size):((slot_within_block+1)*committee_size)]

    def committee_fractions_for_slot(self, slot):
        committee = self.committee_for_slot(slot)
        return ({ i for i in committee if self.scenario.is_adversarial(i) }, { i for i in committee if self.scenario.is_honest(i) })

    def proposer_for_slot(self, slot):
        committee = self.committee_for_slot(slot)
        return committee[0]

    def role_assignment_for_attack(self):
        # slots 0 and 1 need to have adversarial proposers who will propose two competing blocks
        # and will show them to honest validators only at the beginning of slot 2
        # (with this modification, it becomes harder to launch the attack, but there is no harm
        # in launching it over and over again, as there is no formal equivocation anymore)
        adv_proposer_slot0 = None
        adv_proposer_slot1 = None

        # make sure the proposers in slots 0 and 1 are adversarial
        prop0 = self.proposer_for_slot(0)
        prop1 = self.proposer_for_slot(1)
        if not (self.scenario.is_adversarial(prop0) and self.scenario.is_adversarial(prop1)):
            # print(" -> proposers in slots 0 and 1 are not adversarial")
            return (False, None)
        else:
            adv_proposer_slot0 = prop0
            adv_proposer_slot1 = prop1

        return (True, (adv_proposer_slot0, adv_proposer_slot1,))

    def is_attack_feasible(self):
        (ret, roles) = self.role_assignment_for_attack()
        return ret


@dataclass
class MeasuredGossipPropagationDelayModel(object):
    samples: list

    @classmethod
    def load(cls, filename, node=0):
        # these gossip propagation delay samples were obtained as follows:
        # nodes were connected in a libp2p gossipsub swarm; some nodes send beacon messages;
        # all nodes log when they receive each message for the first time; later, the logs
        # are collected and for each message and each receiver the delay is recorded;
        # the samples are grouped first by sender, then by message, then by receiver.
        # here, we load the set of messages sent by a particular sending node; the
        # propagation delay for adversarial messages to their receivers is modelled by
        # using the measured delays of a randomly chosen message of that sender, to
        # a randomly chosen receiver (but without replacement of receivers);
        # MeasuredGossipPropagationDelayModel handles the sampling of messages,
        # MeasuredGossipPropagationDelayModelInstance handles sampling receivers.
        all_samples = pickle.load(open(filename, "rb"))
        return cls(all_samples[sorted(all_samples.keys())[node]])

    def sample(self, rng):
        return MeasuredGossipPropagationDelayModelInstance(rng.choice(self.samples))


@dataclass
class MeasuredGossipPropagationDelayModelInstance(object):
    samples: list

    def sample(self, rng, k):
        return rng.sample(self.samples, k)


def run_attack_simulation(scenario, gossip_propagation_samples, num_slots_simulate, rnd_try, T_delay):
    VOTED_N = 0   # never
    VOTED_G = 1   # genesis
    VOTED_L = 2   # left
    VOTED_R = 3   # right

    def balance(lmd):
        return (lmd.count(VOTED_L), lmd.count(VOTED_R))

    def leading(lmd):
        if lmd.count(VOTED_L) > lmd.count(VOTED_R):
            return VOTED_L
        elif lmd.count(VOTED_L) < lmd.count(VOTED_R):
            return VOTED_R
        elif lmd.count(VOTED_L) == lmd.count(VOTED_R):
            return None
        else:
            assert False


    balances = []

    schedule = RandomSchedule(scenario, 42 + rnd_try)
    (attack_feasible, attack_roles) = schedule.role_assignment_for_attack()
    if not attack_feasible:
        return (0, [])


    (adv_proposer_slot0, adv_proposer_slot1,) = attack_roles
    # print("adversarial proposer in slot 0:", adv_proposer_slot0)
    # print("adversarial proposer in slot 1:", adv_proposer_slot1)


    # set up latest votes as seen globally
    lmd = [ VOTED_N for i in scenario.all_parties() ]

    # set up global randomness (for reproducibility)
    rng = random.Random(42*42 + rnd_try)


    # keep track of which adversarial committee members can still release a new vote
    cm_adv_can_effect_2_L = set()
    cm_adv_can_effect_2_R = set()
    cm_adv_can_effect_1_L = set()
    cm_adv_can_effect_1_R = set()


    for slot in range(0, num_slots_simulate):
        (cm_adv, cm_hon) = schedule.committee_fractions_for_slot(slot)

        if slot == 0:
            # in slots 0 and 1 the adversary is proposer and proposes two conflicting
            # blocks, but does not release them until the beginning of slot 2;
            # in slot 0, the proposal is LEFT, so adversarial validators from that
            # slot can later only reveal votes for LEFT

            cm_adv_can_effect_2_L |= { i for i in cm_adv if lmd[i] == VOTED_R }
            cm_adv_can_effect_1_L |= { i for i in cm_adv if lmd[i] == VOTED_N }

        elif slot == 1:
            # in slots 0 and 1 the adversary is proposer and proposes two conflicting
            # blocks, but does not release them until the beginning of slot 2;
            # in slot 1, the proposal is RIGHT, so adversarial validators from that
            # slot can later reveal votes for either LEFT or RIGHT

            cm_adv_can_effect_2_L |= { i for i in cm_adv if lmd[i] == VOTED_R }
            cm_adv_can_effect_2_R |= { i for i in cm_adv if lmd[i] == VOTED_L }
            cm_adv_can_effect_1_L |= { i for i in cm_adv if lmd[i] == VOTED_N }
            cm_adv_can_effect_1_R |= { i for i in cm_adv if lmd[i] == VOTED_N }

        elif slot >= 2:
            # slot >= 2: chains are balanced; tie breaks in favor of LEFT block vs.
            # RIGHT block; adv uses sway vote from earlier slots to tip balance
            # in favor of RIGHT block; => if T > T_delay, then validator votes
            # LEFT (favored by tie break), otherwise validator votes RIGHT (as it
            # has seen the tipping vote before proceeding to vote)

            assert not leading(lmd)

            # find an adversarial validator who can still release a vote for RIGHT
            # `in the past'; release this vote T_delay before honest validators take
            # a vote, so that ideally roughly half of honest validators in this slot
            # vote LEFT and the other half votes RIGHT, so that the adversary has a
            # good chance to rebalance to a tie with remaining adversarial votes
            i_swayer = None
            if len(cm_adv_can_effect_1_R) > 0:
                i_swayer = cm_adv_can_effect_1_R.pop()
            elif len(cm_adv_can_effect_2_R) > 0:
                i_swayer = cm_adv_can_effect_2_R.pop()
            else:
                # raise Exception("not enough adversarial validators to balance -- liveness attack over!")
                return (slot, balances)

            lmd_beforeT = copy.copy(lmd)
            lmd_afterT = copy.copy(lmd)

            lmd_afterT[i_swayer] = VOTED_R
            lmd[i_swayer] = VOTED_R

            cm_adv_can_effect_2_L = cm_adv_can_effect_2_L - {i_swayer,}
            cm_adv_can_effect_2_R = cm_adv_can_effect_2_R - {i_swayer,}
            cm_adv_can_effect_1_L = cm_adv_can_effect_1_L - {i_swayer,}
            cm_adv_can_effect_1_R = cm_adv_can_effect_1_R - {i_swayer,}

            assert not leading(lmd_beforeT)
            assert leading(lmd_afterT) == VOTED_R

            # sample the propagation delays for a random message
            gossip_propagation_instance = gossip_propagation_samples.sample(rng)
            # for the chosen message, sample the propagation delays of random receivers
            gossip_propagation_delays = gossip_propagation_instance.sample(rng, len(cm_hon))
            for (i, T) in zip(cm_hon, gossip_propagation_delays):
                if T > T_delay:
                    # votes LEFT
                    lmd[i] = VOTED_L

                else:
                    # votes RIGHT
                    lmd[i] = VOTED_R

            # check and record the balance
            # print(f"slot {slot} balance after honest votes:", balance(lmd))
            balances.append(balance(lmd))

            # add current committee members to adversarial validators with outstanding
            # votes; these validators can eventually release votes to balance the chains,
            # now or in the future
            cm_adv_can_effect_2_L |= { i for i in cm_adv if lmd[i] == VOTED_R }
            cm_adv_can_effect_2_R |= { i for i in cm_adv if lmd[i] == VOTED_L }
            cm_adv_can_effect_1_L |= { i for i in cm_adv if lmd[i] == VOTED_N }
            cm_adv_can_effect_1_R |= { i for i in cm_adv if lmd[i] == VOTED_N }

        else:
            assert False

        # attempt to re-balance (greedily)
        while leading(lmd):
            i = None

            if balance(lmd)[0] - balance(lmd)[1] >= 2:
                # >= 2 votes more for Left
                if len(cm_adv_can_effect_2_R) > 0:
                    i = cm_adv_can_effect_2_R.pop()
                    lmd[i] = VOTED_R
                elif len(cm_adv_can_effect_1_R) > 0:
                    i = cm_adv_can_effect_1_R.pop()
                    lmd[i] = VOTED_R
                else:
                    # raise Exception("not enough adversarial validators to balance -- liveness attack over!")
                    return (slot, balances)
            elif balance(lmd)[0] - balance(lmd)[1] >= 1:
                # >= 2 votes more for Left
                if len(cm_adv_can_effect_1_R) > 0:
                    i = cm_adv_can_effect_1_R.pop()
                    lmd[i] = VOTED_R
                else:
                    # raise Exception("not enough adversarial validators to balance -- liveness attack over!")
                    return (slot, balances)
            elif balance(lmd)[0] - balance(lmd)[1] <= -2:
                # >= 2 votes more for Left
                if len(cm_adv_can_effect_2_L) > 0:
                    i = cm_adv_can_effect_2_L.pop()
                    lmd[i] = VOTED_L
                elif len(cm_adv_can_effect_1_L) > 0:
                    i = cm_adv_can_effect_1_L.pop()
                    lmd[i] = VOTED_L
                else:
                    # raise Exception("not enough adversarial validators to balance -- liveness attack over!")
                    return (slot, balances)
            elif balance(lmd)[0] - balance(lmd)[1] <= -1:
                # >= 2 votes more for Left
                if len(cm_adv_can_effect_1_L) > 0:
                    i = cm_adv_can_effect_1_L.pop()
                    lmd[i] = VOTED_L
                else:
                    # raise Exception("not enough adversarial validators to balance -- liveness attack over!")
                    return (slot, balances)
            else:
                assert False

            assert not i is None
            cm_adv_can_effect_2_L -= {i,}
            cm_adv_can_effect_2_R -= {i,}
            cm_adv_can_effect_1_L -= {i,}
            cm_adv_can_effect_1_R -= {i,}

        # check the balance
        # print(f"slot {slot} balance after adversarial balancing votes:", balance(lmd))

        assert not leading(lmd)

    return (slot, balances)




# parameters of the scenario
scenario = Scenario(32, 4096, int(0.15 * 4096))   # adversarial fraction: 15%

# load gossip propagation measurements
# these gossip propagation delay samples were obtained as follows:
# 750 nodes, each on an aws ec2 m6g.medium instance (50 instances each
# in all 15 aws regions that supported m6g.medium as of 21-apr-2021:
# eu-north-1, eu-central-1, eu-west-1, eu-west-2, ap-northeast-1,
# ap-northeast-2, ap-southeast-1, ap-southeast-2, ap-south-1, sa-east-1,
# ca-central-1, us-east-1, us-east-2, us-west-1, us-west-2);
# connected via libp2p gossipsub (each node randomly connected to 10 nodes);
# five nodes with lowest instance id sent beacon messages with inter-transmission
# times uniformly distributed [0,5] seconds; all nodes log when they receive each
# message for the first time; later, the logs are collected and for each message
# and each receiver the delay is recorded; the samples are grouped first by sender
# of the message, then by the message, and then by the receiver; in the attack
# simulation, a certain sending node is picked to be the adversary, and the
# propagation delay for adversarial messages to their receivers is modelled by
# using the measured delays of a randomly chosen message of that sender, to
# a randomly chosen receiver (but without replacement of receivers)
# sending nodes:
# node 0: id: i-000ff4115b14690cb, location: us-east-2, optimal T_delay: ~100ms
# node 1: id: i-00108a6bf2add4e7f, location: ap-northeast-1, optimal T_delay: ~130ms
# node 2: id: i-00120f892976c76e2, location: us-east-1, optimal T_delay: ~85ms
# node 3: id: i-0015999915e28fcfb, location: ap-northeast-1, optimal T_delay: ~140ms
# node 4: id: i-0017d5257cae82d0a, location: ap-northeast-2, optimal T_delay: ~165ms
gossip_propagation_samples = MeasuredGossipPropagationDelayModel.load("samples_simplified_afcf8c74bc552b0506a3a1c58f74c2ac.pickle", node=4)

# attack horizon (simulate attack for 25 epochs)
num_slots_simulate = 25 * scenario.C


# grid search the optimal delay parameter for the adversary
performance = []
for T_delay in [ x*0.001 for x in range(80, 180+1, 5) ]:
    print(f"* T_delay = {int(T_delay*1000)}ms")

    attack_outcomes = []
    rnd_tries = 0
    while len([ r for r in attack_outcomes if r > 0 ]) < 10:
        (runtime, balances) = run_attack_simulation(scenario, gossip_propagation_samples, num_slots_simulate, rnd_tries, T_delay)
        if runtime > 0:
            print(f"attack launched at random sample {rnd_tries}, stalled liveness for {runtime} slots")
        attack_outcomes.append(runtime)
        rnd_tries += 1

    print(f"-> attack launched in {len([ r for r in attack_outcomes if r > 0 ])} of {len(attack_outcomes)} epochs = {int(len([ r for r in attack_outcomes if r > 0 ]) / len(attack_outcomes) * 100)}% probability")
    print(f"-> attack stalled liveness for avg of {sum([ r for r in attack_outcomes if r > 0 ])/len([ r for r in attack_outcomes if r > 0 ])} slots")
    print()
    performance.append((T_delay*1000, sum([ r for r in attack_outcomes if r > 0 ])/len([ r for r in attack_outcomes if r > 0 ])))

# print(performance)