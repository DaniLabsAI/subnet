from copy import deepcopy
from dataclasses import replace
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from bittensor_wallet import Keypair

from danilabs_validator.config import Settings,FINNEY_GENESIS
from danilabs_validator.reports import verify,score,ReportError,ReportSettings,ReportClient,SCHEMA,METRICS
from danilabs_validator.worker import run

NOW=1793070000
SETTINGS=Settings(netuid=2)
KEY=Keypair.create_from_seed('0x'+'11'*32)
PUBLIC=KEY.public_key
IDENTITY={'miner-hotkey':{'uid':58,'registration_block':100}}


def document():
    return {'schema':SCHEMA,'metrics_version':METRICS,'network':'finney','genesis':FINNEY_GENESIS,
        'netuid':2,'test_mode':False,'generated_at':NOW-30,'expires_at':NOW+900,
        'window_start':NOW-60-86400,'window_end':NOW-60,'window_basis':'terminal_accounting_received_half_open',
        'report_id':f'sn2-v1-{NOW-60}','miners':[{'hotkey':'miner-hotkey','uid':58,'registration_block':100,
        'completed_requests':5,'failed_requests':0,'client_cancellations':1,'invalid_completed_requests':0,
        'valid_samples':5,'ping_samples':10,'p50_gateway_rtt_us':200000,'p95_gateway_rtt_us':300000,
        'state_samples':5,'ready_state_samples':5,'models':[{'model_id':'openai/gpt-oss-20b',
        'workload':'p_le_1024/o_le_1024','samples':5,'decode_tps_milli':300000,
        'p50_ttft_ms':200,'p95_ttft_ms':250,'input_tokens':100,'output_tokens':1505}]}]}


def signed(doc):
    body=json.dumps(doc,sort_keys=True,separators=(',',':')).encode()
    headers={'X-Dani-Report-Key-ID':hashlib.sha256(PUBLIC).hexdigest()[:16],
             'X-Dani-Report-Signature':base64.b64encode(KEY.sign(body)).decode()}
    return body,headers


def validated():
    return verify(*signed(document()),PUBLIC.hex(),SETTINGS,NOW)


class ReportTests(unittest.TestCase):
    def test_signed_data_scores_and_weights_sum_to_65535(self):
        result=score(validated(),IDENTITY)
        self.assertEqual(result['candidate_weights'],[[58,65535]])
        self.assertEqual(result['component_weights'],{'tps':.5,'ttft':.35,'reliability':.1,'ping':.05})
        self.assertFalse(result['weights_submitted']);self.assertFalse(result['chain_writes'])

    def test_tampering_wrong_key_and_unsigned_reports_rejected(self):
        body,headers=signed(document())
        for b,h in [(body+b' ',headers),(body,{}),(body,headers|{'X-Dani-Report-Key-ID':'wrong'})]:
            with self.assertRaises(ReportError):verify(b,h,PUBLIC.hex(),SETTINGS,NOW)

    def test_stale_wrong_chain_and_changed_window_rejected(self):
        for changes in [{'expires_at':NOW-1},{'generated_at':NOW+31},{'netuid':3},{'test_mode':True},{'schema':'old'}]:
            d=document();d.update(changes)
            with self.assertRaises(ReportError):verify(*signed(d),PUBLIC.hex(),SETTINGS,NOW)
        prev=validated();d=document();d['miners'][0]['failed_requests']=1
        with self.assertRaises(ReportError):verify(*signed(d),PUBLIC.hex(),SETTINGS,NOW,prev)

    def test_duplicate_json_fields_even_when_signed_are_rejected(self):
        body,headers=signed(document());body=body[:-1]+b',"netuid":2}'
        headers['X-Dani-Report-Signature']=base64.b64encode(KEY.sign(body)).decode()
        with self.assertRaises(ReportError):verify(body,headers,PUBLIC.hex(),SETTINGS,NOW)

    def test_recycled_uid_and_inconsistent_sample_counts_rejected(self):
        identity=deepcopy(IDENTITY);identity['miner-hotkey']['registration_block']=101
        with self.assertRaises(ReportError):score(validated(),identity)
        d=validated();d['miners'][0]['valid_samples']=4
        with self.assertRaises(ReportError):score(d,IDENTITY)

    def test_faster_tps_and_lower_ttft_raise_candidate_share(self):
        d=validated();other=deepcopy(d['miners'][0]);other.update(hotkey='other',uid=59)
        other['models'][0].update(decode_tps_milli=600000,p50_ttft_ms=100)
        d['miners'].append(other)
        result=score(d,IDENTITY|{'other':{'uid':59,'registration_block':100}})
        self.assertEqual(sum(w for _,w in result['candidate_weights']),65535)
        self.assertGreater(dict(result['candidate_weights'])[59],dict(result['candidate_weights'])[58])

    def test_unknown_ping_is_not_invented_zero_latency(self):
        d=validated();d['miners'][0].update(ping_samples=0,p50_gateway_rtt_us=None,p95_gateway_rtt_us=None)
        result=score(d,IDENTITY)['scores'][0]
        self.assertIsNone(result['ping_ms']);self.assertEqual(result['cohorts'][0]['components']['ping'],0)

    def test_no_samples_produces_no_candidate_weights(self):
        d=validated();d['miners'][0].update(models=[],completed_requests=0,valid_samples=0)
        self.assertEqual(score(d,IDENTITY)['candidate_weights'],[])

    def test_cached_report_still_rechecks_current_registration(self):
        client=ReportClient(ReportSettings('https://api.danilabs.ai/v1/validator/reports/latest',PUBLIC.hex()),SETTINGS)
        client.previous=validated();client.result=score(client.previous,IDENTITY)
        client.next_poll=time.monotonic()+60
        chain=Mock();chain.substrate.query.side_effect=[59,'miner-hotkey',101]
        with patch('danilabs_validator.reports.time.time',return_value=NOW):
            with self.assertRaises(ReportError):client.poll(chain,{'source_hash':'fresh','source_block':999})
        self.assertEqual(chain.substrate.query.call_count,3)

    def test_policy_configuration_requires_pinned_key_and_https(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'reports.json';config={'url':'https://api.danilabs.ai/v1/validator/reports/latest','public_key_hex':PUBLIC.hex(),'poll_seconds':60}
            p.write_text(json.dumps(config));self.assertEqual(ReportSettings.load(p,'finney').public_key_hex,PUBLIC.hex())
            p.write_text(json.dumps(config|{'url':'http://api.danilabs.ai/v1/validator/reports/latest'}))
            with self.assertRaises(ReportError):ReportSettings.load(p,'finney')

    def test_endpoint_outage_does_not_interrupt_burn_worker(self):
        snapshot={'source_block':1,'source_hash':'hash'}
        with tempfile.TemporaryDirectory() as root:
            settings=replace(SETTINGS,state_file=str(Path(root)/'worker.json'))
            client=Mock();client.poll.side_effect=OSError('outage')
            with patch('danilabs_validator.worker.FinalizedChain') as chain,patch('danilabs_validator.worker.assess') as assess,patch('danilabs_validator.worker.request_burn') as burn,patch('danilabs_validator.reports.ReportSettings.load'),patch('danilabs_validator.reports.ReportClient',return_value=client):
                chain.return_value.snapshot.return_value=snapshot
                assess.return_value={'burn_guard':{'checks_passed':True},'last_epoch_100_percent_miner_burn_verified':True}
                burn.return_value={'status':'maintained'}
                self.assertEqual(run(settings,'unused',count=1),0)
                burn.assert_called_once()
            state=json.loads(Path(settings.state_file).read_text())
            self.assertEqual(state['status'],'healthy');self.assertEqual(state['report_scoring']['status'],'unavailable')
            self.assertIsNone(state['report_scoring']['candidate_weights'])
