#! /usr/bin/env python3

EXPECT_NUM_RECEIVERS = 750


import sys
import re
import pickle
from collections import defaultdict


print(sys.argv)
ID = sys.argv[1]
assert(ID.isalnum())

samples = defaultdict(lambda: {'t_tx': None, 'rxs': []})

for (i_fn, fn) in enumerate(sys.argv[2:]):
    print("File:", i_fn, fn)

    for l in open(fn, 'r').readlines():
        l = l.strip()
        if 'Received by' in l:
            l = l.split('experiment::experiment] ')[1]
            r = re.findall(r'Received by (i-[0-9a-f]+) at (\d+.\d+): Msg { origin: "(i-[0-9a-f]+)", seqno: (\d+), timestamp: (\d+.\d+) }', l)
            assert(len(r) == 1)
            (i_rx, t_rx, i_tx, seqno, t_tx) = r[0]
            t_rx = float(t_rx)
            t_tx = float(t_tx)
            seqno = int(seqno)
            # print('rx', fn, (i_rx, t_rx, i_tx, seqno, t_tx))

            assert({'i_rx': i_rx, 't_rx': t_rx} not in samples[(i_tx, seqno)]['rxs'])
            samples[(i_tx, seqno)]['rxs'].append({'i_rx': i_rx, 't_rx': t_rx})


        elif 'Sent by' in l:
            l = l.split('experiment::experiment] ')[1]
            r = re.findall(r'Sent by (i-[0-9a-f]+) at (\d+.\d+): Msg { origin: "(i-[0-9a-f]+)", seqno: (\d+), timestamp: (\d+.\d+) }', l)
            assert(len(r) == 1)
            (i_tx, t_tx, i_tx2, seqno, t_tx2) = r[0]
            t_tx = float(t_tx)
            t_tx2 = float(t_tx2)
            seqno = int(seqno)
            # print('tx', fn, (i_tx, t_tx, i_tx2, seqno, t_tx2))

            assert(samples[(i_tx, seqno)]['t_tx'] == None)
            samples[(i_tx, seqno)]['t_tx'] = t_tx


pickle.dump(dict(samples), open(f'samples_{ID}.pickle', 'wb'))


samples_simplified = defaultdict(list)

for (k, v) in samples.items():
    t_tx = v['t_tx']
    assert(len(v['rxs']) == EXPECT_NUM_RECEIVERS)
    rxs = [ rx['t_rx'] - v['t_tx'] for rx in sorted(v['rxs'], key=lambda x: x['i_rx']) ]
    samples_simplified[k[0]].append(rxs)


pickle.dump(dict(samples_simplified), open(f'samples_simplified_{ID}.pickle', 'wb'))

