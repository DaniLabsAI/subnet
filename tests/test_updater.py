import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from danilabs_validator.monitor import load_state, save_state
from danilabs_validator.updater import UpdateRejected, Updater, require_commit

A='a'*40
B='b'*40


class UpdaterTests(unittest.TestCase):
    def fixture(self, root):
        cache=Path(root)/'cache'
        cache.mkdir(exist_ok=True)
        return Updater({'branch':'main','cache':str(cache),'releases':str(Path(root)/'releases'),
                        'state_file':str(Path(root)/'state.json'),'initial_commit':A,
                        'repository':'test','worker_state':'never-opened'})

    def fake_command(self, args, **kwargs):
        return Mock(stdout=(B+'\n').encode() if 'rev-parse' in args else b'')

    def test_update_must_pass_tests_then_fresh_health(self):
        with tempfile.TemporaryDirectory() as root:
            updater=self.fixture(root)
            updater.prepare=Mock()
            updater.activate=Mock()
            updater.await_health=Mock(return_value=True)
            with patch('danilabs_validator.updater.command',side_effect=self.fake_command):
                self.assertEqual(updater.once()['status'],'updated')
            updater.prepare.assert_called_once_with(B)
            updater.activate.assert_called_once_with(B)
            self.assertEqual(load_state(updater.state_path)['accepted'],B)
            self.assertNotIn('pending',load_state(updater.state_path))

    def test_failed_candidate_rolls_back_and_is_quarantined(self):
        with tempfile.TemporaryDirectory() as root:
            updater=self.fixture(root)
            updater.prepare=Mock()
            updater.activate=Mock()
            updater.await_health=Mock(side_effect=[False,True])
            with patch('danilabs_validator.updater.command',side_effect=self.fake_command):
                result=updater.once()
                self.assertEqual(result['status'],'rolled_back')
                self.assertEqual(updater.once()['status'],'quarantined')
            self.assertEqual([x.args[0] for x in updater.activate.call_args_list],[B,A])
            self.assertEqual(load_state(updater.state_path)['accepted'],A)

    def test_build_failure_and_fetch_failure_leave_worker_running(self):
        with tempfile.TemporaryDirectory() as root:
            updater=self.fixture(root)
            updater.prepare=Mock(side_effect=UpdateRejected('tests failed'))
            updater.activate=Mock()
            with patch('danilabs_validator.updater.command',side_effect=self.fake_command):
                self.assertEqual(updater.once()['status'],'rejected')
            with patch('danilabs_validator.updater.command',side_effect=OSError('offline')):
                self.assertEqual(updater.once()['status'],'fetch_failed')
            updater.activate.assert_not_called()
            self.assertEqual(updater.state['accepted'],A)

    def test_interrupted_update_restores_last_accepted_release(self):
        with tempfile.TemporaryDirectory() as root:
            updater=self.fixture(root)
            updater.state['pending']=B
            save_state(updater.state_path,updater.state)
            restarted=self.fixture(root)
            restarted.activate=Mock()
            restarted.recover_interrupted()
            restarted.activate.assert_called_once_with(A)
            self.assertNotIn('pending',load_state(restarted.state_path))
            self.assertIn(B,load_state(restarted.state_path)['rejected'])

    def test_only_full_commit_ids_are_accepted(self):
        for sha in ['main','a'*39,'../'+A,'a'*40+';id']:
            with self.subTest(sha=sha), self.assertRaises(UpdateRejected):
                require_commit(sha)
        require_commit(A)


if __name__=='__main__':
    unittest.main()
