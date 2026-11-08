"""Seeded property tests for the deterministic weight vector produced by score().

Validator hosts run this suite inside the updater with the locked dependency
set, so these tests use only the standard library (no hypothesis). Seeds are
fixed, which keeps failures reproducible and the run well inside the updater's
test timeout.
"""
from copy import deepcopy
import random
import unittest

from danilabs_validator.reports import LEGACY_METRICS, METRICS, MODEL_POLICY, score

MODEL = 'openai/gpt-oss-20b'
WORKLOADS = [f'p_{p}/o_{o}' for p in ('le_1024', 'le_8192', 'gt_8192')
             for o in ('le_128', 'le_1024', 'gt_1024')]
SEEDS = range(200)
FULL_WEIGHT = 65535


def model_row(rng, workload, model_id=MODEL):
    samples = rng.randint(1, 50)
    p50_ttft = rng.randint(0, 5000)
    return {'model_id': model_id, 'workload': workload, 'samples': samples,
            'decode_tps_milli': rng.randint(1, 1_000_000),
            'p50_ttft_ms': p50_ttft, 'p95_ttft_ms': p50_ttft + rng.randint(0, 5000),
            'input_tokens': rng.randint(0, 100_000),
            'output_tokens': rng.randint(2 * samples, 2 * samples + 100_000)}


def miner_row(rng, uid, workloads, model_id=MODEL):
    models = [model_row(rng, workload, model_id) for workload in workloads]
    valid = sum(model['samples'] for model in models)
    invalid = rng.randint(0, 5)
    ping_samples = rng.choice([0, rng.randint(1, 100)])
    ping = rng.randint(1, 1_000_000) if ping_samples else None
    states = rng.randint(0, 20)
    return {'hotkey': f'hotkey-{uid}', 'uid': uid, 'registration_block': 100 + uid,
            'completed_requests': valid + invalid, 'failed_requests': rng.randint(0, 20),
            'client_cancellations': rng.randint(0, 5), 'invalid_completed_requests': invalid,
            'valid_samples': valid, 'ping_samples': ping_samples,
            'p50_gateway_rtt_us': ping,
            'p95_gateway_rtt_us': ping + rng.randint(0, 1_000_000) if ping_samples else None,
            'state_samples': states, 'ready_state_samples': rng.randint(0, states),
            'models': models}


def report(miners, metrics=METRICS):
    return {'metrics_version': metrics, 'miners': miners, 'report_id': 'sn2-v2-11000',
            'report_sha256': '0' * 64, 'window_end': 1, 'next_update_estimate': 2,
            'epoch': {'index': 30, 'end_block': 11000}}


def identities(miners):
    return {m['hotkey']: {'uid': m['uid'], 'registration_block': m['registration_block']}
            for m in miners}


def random_report(rng, metrics=METRICS):
    uids = rng.sample(range(256), rng.randint(1, 12))
    miners = [miner_row(rng, uid, rng.sample(WORKLOADS, rng.randint(1, 3))) for uid in uids]
    return report(miners, metrics)


def weights(result):
    return dict(result['candidate_weights'])


class ScoreVectorProperties(unittest.TestCase):
    def test_vector_is_sorted_positive_and_sums_to_full_weight(self):
        for metrics in (METRICS, LEGACY_METRICS):
            for seed in SEEDS:
                with self.subTest(metrics=metrics, seed=seed):
                    doc = random_report(random.Random(seed), metrics)
                    vector = score(doc, identities(doc['miners']))['candidate_weights']
                    uids = [uid for uid, _ in vector]
                    self.assertEqual(uids, sorted(set(uids)))
                    self.assertTrue(set(uids) <= {m['uid'] for m in doc['miners']})
                    self.assertTrue(all(type(w) is int and 0 < w <= FULL_WEIGHT for _, w in vector))
                    self.assertEqual(sum(w for _, w in vector), FULL_WEIGHT)

    def test_vector_ignores_miner_and_model_order(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                doc = random_report(rng)
                shuffled = deepcopy(doc)
                rng.shuffle(shuffled['miners'])
                for miner in shuffled['miners']:
                    rng.shuffle(miner['models'])
                self.assertEqual(score(doc, identities(doc['miners']))['candidate_weights'],
                                 score(shuffled, identities(shuffled['miners']))['candidate_weights'])

    def test_single_cohort_rounding_stays_within_one_unit_of_raw_share(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                workload = rng.choice(WORKLOADS)
                miners = [miner_row(rng, uid, [workload])
                          for uid in rng.sample(range(256), rng.randint(1, 12))]
                result = score(report(miners), identities(miners))
                raw = {row['uid']: row['cohorts'][0]['raw_score'] for row in result['scores']}
                total = sum(raw.values())
                vector = weights(result)
                for uid, value in raw.items():
                    self.assertLess(abs(vector.get(uid, 0) - FULL_WEIGHT * value / total), 1)

    def test_faster_decode_or_first_token_never_loses_more_than_rounding(self):
        # Weight is monotone before rounding. Largest-remainder rounding can move
        # a single unit between miners, so allow exactly that much.
        for field, improve in (('decode_tps_milli', lambda v: v * 2),
                               ('p50_ttft_ms', lambda v: v // 2)):
            for seed in SEEDS:
                with self.subTest(field=field, seed=seed):
                    doc = random_report(random.Random(seed))
                    better = deepcopy(doc)
                    target = better['miners'][0]
                    model = target['models'][0]
                    model[field] = improve(model[field])
                    if field == 'p50_ttft_ms' and model[field] == doc['miners'][0]['models'][0][field]:
                        continue
                    before = score(doc, identities(doc['miners']))
                    after = score(better, identities(better['miners']))
                    uid = target['uid']
                    raw_before = before['scores'][0]['cohorts'][0]['raw_score']
                    raw_after = after['scores'][0]['cohorts'][0]['raw_score']
                    self.assertGreater(raw_after, raw_before)
                    self.assertGreaterEqual(weights(after).get(uid, 0), weights(before).get(uid, 0) - 1)

    def test_unscored_models_and_empty_reports_produce_no_weights(self):
        unknown = 'unreviewed/model'
        self.assertNotIn(unknown, MODEL_POLICY)
        self.assertEqual(score(report([]), {})['candidate_weights'], [])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                rng = random.Random(seed)
                miners = [miner_row(rng, uid, rng.sample(WORKLOADS, rng.randint(1, 3)), unknown)
                          for uid in rng.sample(range(256), rng.randint(1, 12))]
                result = score(report(miners), identities(miners))
                self.assertEqual(result['candidate_weights'], [])
                self.assertTrue(all(row['cohorts'] == [] for row in result['scores']))


if __name__ == '__main__':
    unittest.main()
