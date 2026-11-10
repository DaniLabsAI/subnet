"""Score independently verified samples. This module has no transaction writer."""
from collections import defaultdict
import base64
import math
from pathlib import Path
import re
from statistics import median

from bittensor_wallet import Keypair

from .reports import MAX_BYTES, MAX_DECODE_TPS_MILLI, METRICS, MODEL_POLICY, ReportError, integer, score, strict_json

SCHEMA = 'danilabs.independent-quality.v1'
MIN_SAMPLES_PER_MINER = 5
MIN_MINERS_PER_COHORT = 2


def load_candidates(report, identities, config):
    """An unavailable or stale audit never inherits the previous epoch's vector."""
    unavailable = {'status':'unavailable','candidate_weights':[],'reward_eligible':False}
    max_envelope = 4*((MAX_BYTES+2)//3)+1024
    try:
        with Path(config.quality_evidence_path).open('rb') as source:
            raw = source.read(max_envelope+1)
        if len(raw)>max_envelope:
            return unavailable
        bundle = strict_json(raw)
        if not isinstance(bundle,dict) or set(bundle)!={'body_b64','signature'}:
            return unavailable
        result = qualified_candidates(
            report, identities, base64.b64decode(bundle['body_b64'],validate=True),
            bundle['signature'],verifier_key=config.quality_verifier_key_hex,report_key=config.public_key_hex,
        )
        return {'status':'ready' if result['candidate_weights'] else 'insufficient_coverage',**result}
    except (OSError, ValueError, TypeError, KeyError):
        return unavailable


def _workload(prompt, completion):
    input_class = 'p_le_1024' if prompt <= 1024 else 'p_le_8192' if prompt <= 8192 else 'p_gt_8192'
    output_class = 'o_le_128' if completion <= 128 else 'o_le_1024' if completion <= 1024 else 'o_gt_1024'
    return f'{input_class}/{output_class}'


def qualified_candidates(report, identities, body, signature, *, verifier_key, report_key):
    """Compute a separate dry-run candidate vector from a pinned verifier's evidence.

    The verifier is responsible for independent token measurement and correctness
    evaluation. A miner-signed or report-publisher-signed claim cannot authorize
    the verified vector. The exact signed report digest binds the epoch and chain.
    """
    if (len(body) > MAX_BYTES or not re.fullmatch(r'[a-f0-9]{64}', verifier_key)
            or not re.fullmatch(r'[a-f0-9]{64}', report_key) or verifier_key == report_key):
        raise ReportError('Expected a distinct pinned verifier and bounded evidence')
    try:
        raw_signature = base64.b64decode(signature, validate=True)
        valid = len(raw_signature) == 64 and Keypair(public_key='0x'+verifier_key, crypto_type=1).verify(body,raw_signature)
    except Exception as exc:
        raise ReportError('Invalid independent verifier signature') from exc
    if not valid:
        raise ReportError('Invalid independent verifier signature')
    evidence = strict_json(body)
    if (not isinstance(evidence, dict) or set(evidence) != {'schema','report_sha256','samples'}
            or evidence['schema'] != SCHEMA or evidence['report_sha256'] != report['report_sha256']
            or not isinstance(evidence['samples'], list) or len(evidence['samples']) > 10000):
        raise ReportError('Independent evidence does not match the signed report')

    # Validate finalized miner identities and the report's normal score contract first.
    score(report, identities)
    miners = {m['uid']:m for m in report['miners']}
    seen = set()
    attempts = defaultdict(int)
    failures = defaultdict(int)
    groups = defaultdict(list)
    keys = {'request_id','uid','model_id','finished_at','input_tokens','output_tokens',
            'ttft_ms','decode_ms','token_count_verified','correctness_verified'}
    for row in evidence['samples']:
        if not isinstance(row, dict) or set(row) != keys:
            raise ReportError('Invalid independent sample fields')
        uid = integer(row['uid'], 65535)
        rid = row['request_id']
        model = row['model_id']
        if (uid not in miners or not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',rid)
                or rid in seen or not isinstance(model,str) or model not in MODEL_POLICY
                or not report['window_start'] <= integer(row['finished_at']) < report['window_end']
                or type(row['token_count_verified']) is not bool or type(row['correctness_verified']) is not bool):
            raise ReportError('Sample identity, scope or verification status is invalid')
        seen.add(rid)
        attempts[uid] += 1
        if not (row['token_count_verified'] and row['correctness_verified']):
            failures[uid] += 1
            continue
        prompt, output, ttft, decode = (integer(row[key], limit) for key,limit in (
            ('input_tokens',131072),('output_tokens',131072),('ttft_ms',3600000),('decode_ms',3600000)))
        if prompt+output > 131072 or not prompt:
            raise ReportError('Independent token count is outside model limits')
        # A decode rate outside the score contract, such as buffered tokens sent
        # in one burst, is not valid decode timing. Like a short success, it
        # counts toward reliability but stays out of throughput cohorts, so one
        # miner's timing cannot void the audited vector for every miner.
        if (output < 2 or not decode
                or not decode <= (output-1)*1_000_000 <= MAX_DECODE_TPS_MILLI*decode):
            continue
        groups[model,_workload(prompt,output),uid].append((prompt,output,ttft,decode))

    eligible = defaultdict(dict)
    for (model,workload,uid), rows in groups.items():
        if len(rows) >= MIN_SAMPLES_PER_MINER:
            eligible[model,workload][uid] = rows
    per_miner = defaultdict(list)
    for (model,workload), qualified in sorted(eligible.items()):
        if len(qualified) < MIN_MINERS_PER_COHORT:
            continue
        for uid, rows in sorted(qualified.items()):
            ttft = sorted(r[2] for r in rows)
            per_miner[uid].append({
                'model_id':model,'workload':workload,'samples':len(rows),
                'input_tokens':sum(r[0] for r in rows),'output_tokens':sum(r[1] for r in rows),
                'decode_tps_milli':round(median((r[1]-1)*1_000_000/r[3] for r in rows)),
                'p50_ttft_ms':round(median(ttft)), 'p95_ttft_ms':ttft[math.ceil(len(ttft)*.95)-1],
            })
    audited = []
    for uid, cohorts in sorted(per_miner.items()):
        completed = attempts[uid]-failures[uid]
        valid = sum(c['samples'] for c in cohorts)
        audited.append(miners[uid] | {'completed_requests':completed,'failed_requests':failures[uid],
                                     'client_cancellations':0,'valid_samples':valid,
                                     'invalid_completed_requests':completed-valid,'models':cohorts})
    result = score(report | {'metrics_version':METRICS,'miners':audited}, identities)
    return {'candidate_weights':result['candidate_weights'],'scores':result['scores'],
            'mode':'independent_quality_dry_run','minimum_samples_per_miner':MIN_SAMPLES_PER_MINER,
            'minimum_miners_per_cohort':MIN_MINERS_PER_COHORT,'audited_samples':len(seen),
            'chain_writes':False,'weights_submitted':False,'reward_eligible':False}
