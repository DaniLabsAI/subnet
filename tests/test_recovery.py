from dataclasses import replace
from pathlib import Path
import base64
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from danilabs_validator.burn import BurnBlocked,BurnSigner
from danilabs_validator.config import FINNEY_GENESIS,Settings
from danilabs_validator.custody import CustodyError,SignerPolicy,RUNTIME_REVIEWS
from danilabs_validator.recovery import RecoveryConfig,recover,oci_secret
from danilabs_validator.recovery_guard import Inhibit,control_lock
import test_burn


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        settings,snapshot=test_burn.BurnTests().fixture()
        config=RecoveryConfig(enabled=True,secret_id='ocid1.vaultsecret.oc1.iad.testsecret')
        policy=SignerPolicy(enabled=True,netuid=settings.netuid)
        current={'network':settings.network,'public_hotkey':settings.validator_hotkey,
          'signing_enabled':True,'key_locked':True,'emergency_locked':False,
          'emergency_lock_file':config.disabled_file}
        return settings,snapshot,config,policy,current

    def test_disabled_finney_never_reads_secret_or_contacts_signer(self):
        settings=Settings(netuid=2,weight_submission_mode='legacy-commit-reveal')
        policy=SignerPolicy(network='finney',expected_genesis=FINNEY_GENESIS,netuid=2,
            runtime_spec=484,runtime_source_commit=RUNTIME_REVIEWS[484],enabled=False)
        config=RecoveryConfig(enabled=True,secret_id='ocid1.vaultsecret.oc1.iad.testsecret')
        fetch=Mock();ipc=Mock()
        self.assertEqual(recover(config,settings,policy,fetch=fetch,ipc=ipc)['status'],'disabled')
        fetch.assert_not_called();ipc.assert_not_called()

    def test_unlocked_signer_needs_no_secret_and_wrong_identity_is_refused(self):
        settings,_,config,policy,current=self.fixture();fetch=Mock()
        inhibit=Mock();inhibit.active.return_value=False
        ipc=Mock(return_value={**current,'key_locked':False})
        self.assertEqual(recover(config,settings,policy,fetch=fetch,ipc=ipc,inhibit=inhibit)['status'],'unlocked')
        fetch.assert_not_called()
        for update in [{'network':'finney'},{'public_hotkey':'other'}, {'emergency_lock_file':None}]:
            ipc.return_value={**current,**update}
            with self.assertRaises(CustodyError):recover(config,settings,policy,fetch=fetch,ipc=ipc,inhibit=inhibit)
        fetch.assert_not_called()

    def test_secret_outage_retries_without_unlocking_and_redacts_exception_text(self):
        settings,_,config,policy,current=self.fixture()
        inhibit=Mock();inhibit.active.return_value=False
        fetch=Mock(side_effect=RuntimeError('sensitive-response-must-not-be-logged'))
        ipc=Mock(return_value=current)
        result=recover(config,settings,policy,fetch=fetch,ipc=ipc,inhibit=inhibit)
        self.assertEqual(result['status'],'retrying');self.assertTrue(result['secret_fetch_attempted'])
        self.assertNotIn('sensitive-response',json.dumps(result));self.assertEqual(ipc.call_count,1)

    def test_success_uses_local_ipc_without_retaining_password_in_request_or_result(self):
        settings,_,config,policy,current=self.fixture();inhibit=Mock();inhibit.active.return_value=False
        received=[];retained=[]
        def ipc(_,message):
            received.append(dict(message));retained.append(message)
            return current if message['action']=='status' else {**current,'key_locked':False,'status':'unlocked'}
        result=recover(config,settings,policy,fetch=lambda _:'unit-fixture-password',ipc=ipc,inhibit=inhibit)
        self.assertTrue(result['recovered']);self.assertEqual(received[-1]['password'],'unit-fixture-password')
        self.assertNotIn('password',retained[-1]);self.assertNotIn('unit-fixture-password',json.dumps(result))

    def test_emergency_lock_during_secret_fetch_prevents_unlock(self):
        settings,_,config,policy,current=self.fixture();inhibit=Mock();inhibit.active.side_effect=[False,True]
        ipc=Mock(return_value=current)
        result=recover(config,settings,policy,fetch=lambda _:'unit-fixture',ipc=ipc,inhibit=inhibit)
        self.assertEqual(result['status'],'emergency_locked');self.assertEqual(ipc.call_count,1)

    def test_durable_lock_survives_new_guard_and_controls_burn_before_any_rpc_or_signature(self):
        settings,_,config,policy,current=self.fixture()
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve();root.chmod(0o700)
            guard=Inhibit(root/'disabled',owner_uid=os.geteuid())
            self.assertFalse(guard.active());guard.disable()
            fresh=Inhibit(root/'disabled',owner_uid=os.geteuid());self.assertTrue(fresh.active())
            fetch=Mock();ipc=Mock()
            self.assertEqual(recover(config,settings,policy,fetch=fetch,ipc=ipc,inhibit=fresh)['status'],'emergency_locked')
            fetch.assert_not_called();ipc.assert_not_called()
            keys=Mock(is_unlocked=True)
            keys.lock.side_effect=lambda:setattr(keys,'is_unlocked',False)
            signer=BurnSigner(settings,str(root/'signer-state'),policy=policy,keys=keys,inhibit=fresh)
            signer.chain.snapshot=Mock(side_effect=AssertionError('No RPC while emergency locked'))
            self.assertEqual(signer.maintain()['status'],'emergency_locked')
            self.assertTrue(signer.key_status()['key_locked'])
            with self.assertRaises(BurnBlocked):signer.unlock('not used')
            with self.assertRaises(BurnBlocked):signer.submit('set_weights',{}, {})
            signer.chain.snapshot.assert_not_called();keys.signing_key.assert_not_called()
            fresh.resume();self.assertFalse(guard.active())

    def test_recovery_controls_refuse_symlinks_and_unsafe_parent(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root).resolve();root.chmod(0o700);guard=Inhibit(root/'disabled',owner_uid=os.geteuid())
            guard.path.symlink_to(root/'other')
            self.assertTrue(guard.active())
            with self.assertRaises(OSError):guard.disable()
            with self.assertRaises(CustodyError):guard.resume()
            guard.path.unlink();root.chmod(0o777)
            with self.assertRaises(CustodyError):guard.active()
            root.chmod(0o700)
            with control_lock(root/'control.lock',owner_uid=os.geteuid()):
                self.assertEqual((root/'control.lock').stat().st_mode&0o777,0o600)

    def test_secret_bundle_pins_identity_version_and_encoding(self):
        import sys,types
        cfg=RecoveryConfig(enabled=True,secret_id='ocid1.vaultsecret.oc1.iad.testsecret')
        content=types.SimpleNamespace(content_type='BASE64',content=base64.b64encode(b'unit-password').decode())
        response=types.SimpleNamespace(secret_id=cfg.secret_id,version_number=1,secret_bundle_content=content)
        client=Mock();client.get_secret_bundle.return_value.data=response
        sdk=types.SimpleNamespace(auth=types.SimpleNamespace(signers=types.SimpleNamespace(InstancePrincipalsSecurityTokenSigner=Mock())),
            secrets=types.SimpleNamespace(SecretsClient=Mock(return_value=client)),retry=types.SimpleNamespace(NoneRetryStrategy=Mock()))
        with patch.dict(sys.modules,{'oci':sdk}):
            self.assertEqual(oci_secret(cfg),'unit-password')
            response.version_number=2
            with self.assertRaises(CustodyError):oci_secret(cfg)
        with self.assertRaises(CustodyError):replace(cfg,secret_version=0).validate()
        with self.assertRaises(CustodyError):replace(cfg,secret_id='latest').validate()
