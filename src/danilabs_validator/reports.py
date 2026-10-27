"""Verify signed HTTP measurements and calculate deterministic candidate weights.

No SSH, wallet, signer socket or extrinsic writer exists in this module.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import ssl
import time
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler, ProxyHandler

import certifi
from bittensor_wallet import Keypair

from .chain import value

SCHEMA='danilabs.validator-report.v1'
METRICS='gateway-terminal-v1'
POLICY_VERSION='performance-v2-tps50-ttft35-reliability10-ping5'
MODEL_POLICY={'openai/gpt-oss-20b':{'tps':300,'ttft_ms':500,'budget':1}}
COMPONENT_WEIGHTS={'tps':.50,'ttft':.35,'reliability':.10,'ping':.05}
MAX_BYTES=2*1024*1024


class ReportError(ValueError):
    pass


def strict_json(raw):
    def pairs(items):
        result={}
        for key,val in items:
            if key in result:raise ReportError('Duplicate JSON field')
            result[key]=val
        return result
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ReportError('Non-finite JSON number')))


@dataclass(frozen=True)
class ReportSettings:
    url:str
    public_key_hex:str
    poll_seconds:int=60

    @classmethod
    def load(cls,path,network):
        obj=strict_json(Path(path).read_bytes())
        if set(obj)!={'url','public_key_hex','poll_seconds'}:raise ReportError('Invalid report configuration fields')
        result=cls(**obj)
        endpoint=urlsplit(result.url)
        if (not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
                or endpoint.path!='/v1/validator/reports/latest'):
            raise ReportError('Expected a credential-free validator report endpoint')
        if network=='finney' and endpoint.scheme!='https':raise ReportError('Finney reports require HTTPS')
        if network=='localnet' and (endpoint.scheme!='http' or endpoint.hostname!='127.0.0.1'):
            raise ReportError('Localnet reports require explicit loopback HTTP')
        if not re.fullmatch('[a-f0-9]{64}',result.public_key_hex):raise ReportError('Pin an sr25519 public key')
        if type(result.poll_seconds) is not int or not 15<=result.poll_seconds<=300:raise ReportError('Invalid report poll interval')
        return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def verify(body,headers,public_key_hex,settings,now,previous=None):
    if len(body)>MAX_BYTES:raise ReportError('Report exceeds size limit')
    public=bytes.fromhex(public_key_hex)
    key_id=hashlib.sha256(public).hexdigest()[:16]
    if headers.get('X-Dani-Report-Key-ID')!=key_id:raise ReportError('Report key differs from its configured pin')
    try:
        signature=base64.b64decode(headers.get('X-Dani-Report-Signature',''),validate=True)
        if len(signature)!=64 or not Keypair(public_key='0x'+public.hex(),crypto_type=1).verify(body,signature):
            raise ReportError('Invalid report signature')
    except Exception as exc:
        raise ReportError('Report signature is invalid') from exc
    report=strict_json(body)
    if (report.get('schema')!=SCHEMA or report.get('metrics_version')!=METRICS
            or report.get('network')!=settings.network or report.get('genesis')!=settings.expected_genesis
            or report.get('netuid')!=settings.netuid or report.get('test_mode') is not (settings.network=='localnet')):
        raise ReportError('Report schema or chain pin mismatch')
    start,end,generated,expires=[report.get(k) for k in ['window_start','window_end','generated_at','expires_at']]
    if (not all(type(v) is int for v in [start,end,generated,expires]) or end-start!=86400
            or end>now or not 0<=generated-end<=1200 or generated>now+30
            or not now<expires<=end+1200 or now-generated>1200):
        raise ReportError('Report is stale, future dated or has an invalid window')
    if report.get('window_basis')!='terminal_accounting_received_half_open':raise ReportError('Unknown report window semantics')
    report_id=f'sn{settings.netuid}-v1-{end}'
    if report.get('report_id')!=report_id:raise ReportError('Report ID does not match its window')
    digest=hashlib.sha256(body).hexdigest()
    if previous:
        if end<previous['window_end']:raise ReportError('Report rolled back')
        if end==previous['window_end'] and digest!=previous['report_sha256']:raise ReportError('Report changed within an immutable window')
    miners=report.get('miners')
    if not isinstance(miners,list) or len(miners)>256:raise ReportError('Invalid miner report list')
    report['report_sha256']=digest
    return report


def integer(v,maximum=2**63-1):
    if type(v) is not int or not 0<=v<=maximum:raise ReportError('Invalid metric count')
    return v


def score(report,identities):
    scores=[];cohorts={};seen=set();uids=set()
    for miner in report['miners']:
        hotkey=miner['hotkey'];uid=integer(miner['uid'],65535)
        if hotkey in seen or uid in uids:raise ReportError('Duplicate miner identity')
        seen.add(hotkey);uids.add(uid)
        if identities.get(hotkey)!={'uid':uid,'registration_block':miner['registration_block']}:
            raise ReportError('Finalized miner registration differs from report')
        completed,failed,cancelled,invalid,samples=[integer(miner[k]) for k in [
            'completed_requests','failed_requests','client_cancellations','invalid_completed_requests','valid_samples']]
        if invalid+samples!=completed:raise ReportError('Completion counts are inconsistent')
        reliability=samples/(completed+failed) if completed+failed else 0
        ping_samples=integer(miner['ping_samples'])
        ping=miner['p50_gateway_rtt_us']
        p95=miner['p95_gateway_rtt_us']
        if ping_samples:
            integer(ping,120_000_000);integer(p95,120_000_000)
            if not 0<ping<=p95:raise ReportError('Invalid ping distribution')
        elif ping is not None or p95 is not None:raise ReportError('Ping lacks measurement samples')
        states=integer(miner['state_samples']);ready=integer(miner['ready_state_samples'])
        if ready>states:raise ReportError('Invalid observed readiness counts')
        ping_factor=250_000/(250_000+ping) if ping_samples else 0
        parts=[];buckets=set();model_samples=0
        for model in miner['models']:
            model_id=model['model_id'];bucket=model['workload'];key=(model_id,bucket)
            if key in buckets:raise ReportError('Duplicate workload cohort')
            buckets.add(key)
            if not re.fullmatch(r'p_(?:le_1024|le_8192|gt_8192)/o_(?:le_128|le_1024|gt_1024)',bucket):raise ReportError('Unknown workload definition')
            n=integer(model['samples']);model_samples+=n
            tps=integer(model['decode_tps_milli'],100_000_000)/1000
            ttft=integer(model['p50_ttft_ms'],3_600_000)
            p95ttft=integer(model['p95_ttft_ms'],3_600_000)
            tokens=integer(model['output_tokens']);integer(model['input_tokens'])
            if not n or not tps or not 0<=ttft<=p95ttft or tokens<2*n:raise ReportError('Insufficient or inconsistent inference samples')
            target=MODEL_POLICY.get(model_id)
            if target is None:continue
            components={'tps':tps/(tps+target['tps']),'ttft':target['ttft_ms']/(target['ttft_ms']+ttft),
                        'reliability':reliability,'ping':ping_factor}
            raw=sum(COMPONENT_WEIGHTS[k]*components[k] for k in COMPONENT_WEIGHTS)
            part={'model_id':model_id,'workload':bucket,'samples':n,'output_tokens':tokens,
                  'decode_tps':tps,'ttft_ms':ttft,'components':components,'raw_score':raw}
            parts.append(part)
            cohorts.setdefault(key,[]).append((uid,raw,tokens))
        if model_samples!=samples:raise ReportError('Model sample counts disagree with completion counts')
        scores.append({'uid':uid,'hotkey':hotkey,'registration_block':miner['registration_block'],
            'valid_samples':samples,'failed_requests':failed,'client_cancellations_excluded':cancelled,
            'completion_reliability':round(reliability,6),'ping_samples':ping_samples,'ping_ms':None if ping is None else ping/1000,
            'observed_ready_fraction':None if not states else ready/states,'cohorts':parts})
    shares={uid:0.0 for uid in uids}
    active_models={k[0] for k in cohorts}
    model_budget=sum(MODEL_POLICY[k]['budget'] for k in active_models)
    for (model,bucket),rows in sorted(cohorts.items()):
        volume=sum(tokens for _,_,tokens in rows)
        model_volume=sum(tokens for (m,_),group in cohorts.items() if m==model for _,_,tokens in group)
        raw_total=sum(raw for _,raw,_ in rows)
        budget=(MODEL_POLICY[model]['budget']/model_budget)*(volume/model_volume) if model_volume else 0
        for uid,raw,_ in rows:
            shares[uid]+=budget*raw/raw_total if raw_total else 0
    units={uid:math.floor(share*65535) for uid,share in shares.items() if share>0}
    remaining=65535-sum(units.values()) if units else 0
    order=sorted(units,key=lambda uid:(-(shares[uid]*65535-units[uid]),uid))
    for uid in order[:remaining]:units[uid]+=1
    return {'policy_version':POLICY_VERSION,'component_weights':COMPONENT_WEIGHTS,'scores':scores,
        'candidate_weights':[[uid,units[uid]] for uid in sorted(units) if units[uid]],
        'chain_writes':False,'weights_submitted':False,'mode':'score_only_burn_100',
        'report_id':report['report_id'],'report_sha256':report['report_sha256'],'window_end':report['window_end'],
        'expires_at':report['expires_at'],'quality_verification':'not_provided_by_performance_metrics'}


class ReportClient:
    def __init__(self,config,settings):
        self.config,self.settings=config,settings
        self.previous=None;self.result=None;self.next_poll=0
        self.opener=build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))

    def poll(self,chain,snapshot):
        now=int(time.time())
        if self.result and time.monotonic()<self.next_poll and now<self.result['expires_at']:
            report=self.previous
            cached=True
        else:
            req=Request(self.config.url,headers={'User-Agent':'DaniLabs-Validator/1.0','Accept':'application/json'})
            with self.opener.open(req,timeout=8) as response:
                report=verify(response.read(MAX_BYTES+1),response.headers,self.config.public_key_hex,self.settings,now,self.previous)
            cached=bool(self.previous and self.previous['report_sha256']==report['report_sha256'])
            self.next_poll=time.monotonic()+self.config.poll_seconds
        # Even an unchanged report must not let a recycled UID inherit its score.
        identities={}
        for miner in report['miners']:
            hotkey=miner['hotkey']
            def q(name,args):return value(chain.substrate.query('SubtensorModule',name,args,block_hash=snapshot['source_hash']))
            uid=q('Uids',[self.settings.netuid,hotkey])
            if type(uid) is not int or q('Keys',[self.settings.netuid,uid])!=hotkey:raise ReportError('Finalized UID/hotkey mapping is inconsistent')
            identities[hotkey]={'uid':uid,'registration_block':q('BlockAtRegistration',[self.settings.netuid,uid])}
        result=score(report,identities)
        result.update(finalized_source_block=snapshot['source_block'],finalized_source_hash=snapshot['source_hash'])
        self.previous=report;self.result=result
        return result|{'status':'ready','cached':cached}
