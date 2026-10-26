from dataclasses import replace
from pathlib import Path
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock

from danilabs_validator.burn import BurnBlocked, BurnSigner, preflight
from danilabs_validator.config import FINNEY_GENESIS, LOCALNET_GENESIS, Settings
from danilabs_validator.custody import CustodyError, EncryptedHotkey, RUNTIME_REVIEWS, SignerPolicy
from danilabs_validator.signer import control
import test_burn


class CustodyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from bittensor_wallet import Keypair
        from bittensor_wallet.keyfile import encrypt_keyfile_data, serialized_keypair_to_keyfile_data
        cls.pair=Keypair.create_from_uri('//Bob')  # Public test identity only.
        cls.password='DaniLabs encrypted test identity only 2026'
        cls.plain=serialized_keypair_to_keyfile_data(cls.pair)
        cls.encrypted=encrypt_keyfile_data(cls.plain,password=cls.password)

    def test_encrypted_key_roundtrip_and_lock_do_not_write_plaintext_or_password_env(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'hotkey';p.write_bytes(self.encrypted);p.chmod(0o600)
            before=dict(os.environ)
            key=EncryptedHotkey(str(p),self.pair.ss58_address)
            self.assertFalse(key.is_unlocked)
            with self.assertRaises(CustodyError):key.signing_key()
            key.unlock(self.password)
            self.assertTrue(key.is_unlocked)
            self.assertEqual(key.signing_key().ss58_address,self.pair.ss58_address)
            key.lock()
            self.assertFalse(key.is_unlocked)
            self.assertEqual(p.read_bytes(),self.encrypted)
            self.assertEqual(dict(os.environ),before)
            self.assertEqual(list(Path(root).iterdir()),[p])

    def test_wrong_password_wrong_identity_plaintext_permissions_and_symlink_are_refused(self):
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'hotkey';p.write_bytes(self.encrypted);p.chmod(0o600)
            key=EncryptedHotkey(str(p),self.pair.ss58_address)
            with self.assertRaises(CustodyError) as error:key.unlock('incorrect password')
            self.assertNotIn('incorrect',str(error.exception))
            self.assertFalse(key.is_unlocked)
            p.chmod(0o644)
            with self.assertRaises(CustodyError):key.unlock(self.password)
            p.chmod(0o600);p.write_bytes(self.plain)
            with self.assertRaises(CustodyError):key.unlock(self.password)
            p.write_bytes(self.encrypted)
            from bittensor_wallet import Keypair
            wrong=EncryptedHotkey(str(p),Keypair.create_from_uri('//Alice').ss58_address)
            with self.assertRaises(CustodyError):wrong.unlock(self.password)
            link=Path(root)/'link';link.symlink_to(p)
            with self.assertRaises(OSError):EncryptedHotkey(str(link),self.pair.ss58_address).unlock(self.password)

    def test_disabled_finney_policy_never_opens_a_key_or_calls_rpc(self):
        settings=Settings(netuid=2,weight_submission_mode='legacy-commit-reveal')
        policy=SignerPolicy(network='finney',expected_genesis=FINNEY_GENESIS,netuid=2,
            runtime_spec=484,runtime_source_commit=RUNTIME_REVIEWS[484],version_key=11003,
            keyfile='/nonexistent/production-hotkey',enabled=False)
        with tempfile.TemporaryDirectory() as root:
            keys=Mock(is_unlocked=False)
            signer=BurnSigner(settings,root+'/state.json',policy=policy,keys=keys)
            signer.chain.snapshot=Mock(side_effect=AssertionError('RPC must not be called'))
            self.assertEqual(signer.maintain()['status'],'disabled')
            with self.assertRaises(BurnBlocked):signer.unlock('not used')
            with self.assertRaises(BurnBlocked):signer.submit('set_weights',{}, {})
            signer.chain.snapshot.assert_not_called();keys.unlock.assert_not_called()

    def test_activation_requires_registration_coldkey_and_runtime_review(self):
        settings=Settings(netuid=2,weight_submission_mode='legacy-commit-reveal')
        policy=SignerPolicy(enabled=True,network='finney',expected_genesis=FINNEY_GENESIS,netuid=2,
            runtime_spec=484,runtime_source_commit=RUNTIME_REVIEWS[484],version_key=11003)
        with self.assertRaises(CustodyError):policy.validate(settings)
        settings,snapshot=test_burn.BurnTests().fixture()
        policy=SignerPolicy(enabled=True,netuid=settings.netuid,runtime_spec=484,
            runtime_source_commit=RUNTIME_REVIEWS[484],version_key=11003)
        snapshot.update(runtime_spec_version=484,weights_version=11003)
        self.assertTrue(preflight(snapshot,settings,policy=policy)['burn_guard']['checks_passed'])
        with self.assertRaises(CustodyError):replace(policy,runtime_spec=999).validate(settings)
        with self.assertRaises(BurnBlocked):preflight({**snapshot,'weights_version':0},settings,policy=policy)
        snapshot['validator']['coldkey']='different-custodian'
        with self.assertRaises(BurnBlocked):preflight(snapshot,settings,policy=policy)

    def test_worker_and_updater_cannot_unlock_lock_or_request_arbitrary_signing(self):
        signer=Mock();signer.key_status.return_value={'key_locked':False}
        worker=os.geteuid()+10;outsider=worker+1;lock=threading.RLock()
        self.assertIsNone(control(signer,{'action':'status'},worker,worker,lock))
        for message in ({'action':'unlock','password':'not used'},{'action':'lock'},
                        {'action':'sign','payload':'not used'},{'action':'maintain','netuid':3}):
            with self.assertRaises(BurnBlocked):control(signer,message,worker,worker,lock)
        with self.assertRaises(BurnBlocked):control(signer,{'action':'status'},outsider,worker,lock)
        signer.unlock.assert_not_called();signer.lock.assert_not_called()
        self.assertEqual(control(signer,{'action':'unlock','password':'local test'},0,worker,lock)['status'],'unlocked')
        signer.unlock.assert_called_once_with('local test')

    def test_runtime486_owner_validator_requires_the_exact_runtime_review(self):
        settings,snapshot=test_burn.BurnTests().fixture()
        owner=snapshot['owner']
        settings=replace(settings,validator_hotkey=owner['hotkey'],
            expected_validator_coldkey=owner['coldkey'],
            expected_validator_registration_block=owner['registration_block'],
            weight_submission_mode='legacy-commit-reveal')
        snapshot['validator']={**owner,'validator_permit':True,'stake_weight_raw':1000,
            'last_update':1,'weights_raw':[(owner['uid'],65535)]}
        snapshot.update(runtime_spec_version=486,weights_version=11003,
            commit_reveal_enabled=True,min_allowed_weights=64,max_weight_limit=1000)
        policy=SignerPolicy(enabled=True,netuid=settings.netuid,runtime_spec=486,
            runtime_source_commit=RUNTIME_REVIEWS[486],version_key=11003)
        self.assertTrue(preflight(snapshot,settings,policy=policy)['burn_guard']['checks_passed'])
        with self.assertRaises(BurnBlocked):
            preflight({**snapshot,'runtime_spec_version':484},settings,policy=policy)
        with self.assertRaises(CustodyError):
            replace(policy,runtime_source_commit=RUNTIME_REVIEWS[484]).validate(settings)

    def test_arbitrary_call_and_wrong_burn_destination_never_get_a_private_key(self):
        settings,snapshot=test_burn.BurnTests().fixture()
        with tempfile.TemporaryDirectory() as root:
            keys=Mock(is_unlocked=True)
            signer=BurnSigner(settings,root+'/state.json',keys=keys)
            signer.chain.snapshot=Mock(return_value=snapshot)
            signer.chain.substrate=Mock()
            signer.chain.substrate.get_block_hash.return_value=LOCALNET_GENESIS
            for function,params in [('transfer',{}),('set_weights',{'netuid':73,'dests':[2],
                                        'weights':[65535],'version_key':0})]:
                with self.assertRaises(BurnBlocked):signer.submit(function,params,snapshot)
            keys.signing_key.assert_not_called()
