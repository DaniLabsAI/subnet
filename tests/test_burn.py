from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import Mock

from danilabs_validator.burn import BurnBlocked, BurnSigner, commitment_hex, preflight
from danilabs_validator.config import FINNEY_GENESIS, LOCALNET_GENESIS, Settings
from danilabs_validator.health import healthy
from test_observer import FakeSubstrate, SETTINGS
from danilabs_validator.chain import FinalizedChain


class BurnTests(unittest.TestCase):
    def test_sdk_h256_commitment_encodings(self):
        expected='0x'+bytes(range(32)).hex()
        for raw in (expected, bytes(range(32)), tuple(range(32)), (tuple(range(32)),)):
            self.assertEqual(commitment_hex(raw),expected)
        for raw in ('invalid', ((256,)*32,), (True,)*32, None):
            self.assertIsNone(commitment_hex(raw))

    def fixture(self):
        settings = replace(SETTINGS, network='localnet', expected_genesis=LOCALNET_GENESIS,
                           chain_endpoint='ws://127.0.0.1:19944',expected_validator_coldkey='validator-coldkey')
        fake = FakeSubstrate()
        fake.genesis = LOCALNET_GENESIS
        snapshot = FinalizedChain(settings, fake).snapshot()
        snapshot.update(runtime_spec_version=482, weights_version=0, activity_cutoff=100,
                        epoch_index=3, reveal_period_epochs=1)
        return settings, snapshot

    def test_no_finney_writer_can_be_constructed(self):
        with self.assertRaises(BurnBlocked):
            BurnSigner(SETTINGS, '/path/never/opened')
        with self.assertRaises(ValueError):
            replace(SETTINGS, network='localnet').validate()
        # Observer configuration may describe Finney commit/reveal; it does not
        # authorize a signer or unlock a key.
        replace(SETTINGS, weight_submission_mode='legacy-commit-reveal').validate()

    def test_unsafe_runtime_or_identity_never_passes_signer_preflight(self):
        settings, snapshot = self.fixture()
        self.assertTrue(preflight(snapshot, settings)['burn_guard']['checks_passed'])
        for change in [{'genesis': FINNEY_GENESIS}, {'runtime_spec_version': 483},
                       {'weights_version': 1}, {'mechanism_count': 2},
                       {'commit_reveal_enabled': True}, {'max_weight_limit': 30000},
                       {'min_allowed_weights': 2}, {'recycle_or_burn_raw': {'Recycle': []}}]:
            with self.subTest(change=change), self.assertRaises(BurnBlocked):
                preflight({**snapshot, **change}, settings)
        for field, new in [('validator_permit', False), ('registration_block', 999),
                           ('stake_weight_raw', 0), ('hotkey', 'different')]:
            changed = deepcopy(snapshot)
            changed['validator'][field] = new
            with self.subTest(field=field), self.assertRaises(BurnBlocked):
                preflight(changed, settings)

    def test_writer_can_repair_a_row_without_treating_it_as_burn_proof(self):
        settings, snapshot = self.fixture()
        snapshot['validator']['weights_raw'] = [(2,65535)]
        result = preflight(snapshot, settings)
        self.assertTrue(result['burn_guard']['checks_passed'])
        self.assertFalse(result['burn_guard']['validator_row_100_percent_to_owner'])
        self.assertIsNone(result['last_epoch_100_percent_miner_burn_verified'])
        with tempfile.TemporaryDirectory() as folder:
            signer = BurnSigner(settings, folder+'/signer.json',keys=Mock(is_unlocked=True))
            signer.chain.snapshot = lambda: snapshot
            signer.submit = Mock(return_value={'accepted':True})
            result = signer.maintain()
            self.assertEqual(result['status'],'submitted')
            signer.submit.assert_called_once_with('set_weights',
                {'netuid':73,'dests':[1],'weights':[65535],'version_key':0},snapshot)

    def test_rate_limit_and_healthy_row_do_not_create_repeated_transactions(self):
        settings, snapshot = self.fixture()
        snapshot['validator']['last_update'] = 99
        with tempfile.TemporaryDirectory() as folder:
            signer = BurnSigner(settings,folder+'/state.json',keys=Mock(is_unlocked=True))
            signer.chain.snapshot=lambda:snapshot
            signer.submit=Mock()
            self.assertEqual(signer.maintain()['status'],'maintained')
            snapshot['validator']['weights_raw']=[]
            self.assertEqual(signer.maintain()['status'],'rate_limited')
            signer.submit.assert_not_called()

    def test_reveal_resumes_from_saved_commit_without_new_commit_or_key(self):
        settings, snapshot = self.fixture()
        settings = replace(settings,weight_submission_mode='legacy-commit-reveal')
        snapshot['commit_reveal_enabled']=True
        snapshot['epoch_index']=4
        with tempfile.TemporaryDirectory() as folder:
            signer=BurnSigner(settings,folder+'/state.json',keys=Mock(is_unlocked=True))
            signer.chain.snapshot=lambda:snapshot
            signer.chain.substrate=Mock()
            digest='0x'+bytes(range(32)).hex()
            signer.chain.substrate.query.return_value=[[(tuple(range(32)),),3,80,0]]
            signer.state['pending']={'identity':[73,'owner-hotkey',1,10,'validator-hotkey',20],
                'commit_hash':digest,'salt':[1,2,3], 'prepared_block':80,'last_attempt_block':80}
            signer.persist(snapshot)
            restarted=BurnSigner(settings,folder+'/state.json',signer.chain.substrate,keys=Mock(is_unlocked=False))
            restarted.chain.snapshot=lambda:snapshot
            restarted.submit=Mock(return_value={'finalized':True})
            self.assertEqual(restarted.maintain()['status'],'locked')
            restarted.submit.assert_not_called()
            restarted.keys.is_unlocked=True
            self.assertEqual(restarted.maintain()['status'],'revealed')
            restarted.submit.assert_called_once_with('reveal_weights',{
                'netuid':73,'uids':[1],'values':[65535],'salt':[1,2,3],'version_key':0},snapshot)
            self.assertNotIn('pending',restarted.state)

    def test_new_release_cannot_pass_using_old_or_stale_heartbeat(self):
        state={'release_commit':'new','status':'healthy','network':'localnet',
               'heartbeat_at':datetime.now(timezone.utc).isoformat(),
               'burn_guard':{'checks_passed':True},'snapshot':{'source_hash':'0xabc','genesis':LOCALNET_GENESIS}}
        self.assertTrue(healthy(state,'new'))
        self.assertFalse(healthy(state,'old'))
        self.assertFalse(healthy({**state,'heartbeat_at':(datetime.now(timezone.utc)-timedelta(seconds=200)).isoformat()},'new'))
        self.assertFalse(healthy({**state,'snapshot':{'source_hash':''}},'new'))
        self.assertFalse(healthy(None,'new'))


if __name__=='__main__':
    unittest.main()
