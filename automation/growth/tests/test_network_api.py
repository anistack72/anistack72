import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from growth.network import Journal, NetworkError
from growth.network_api import Account, ApiError, Checkpoint, Http, execute, export_state, restore_state, STATE_PATH

NOW = dt.datetime(2026, 11, 24, 19, 30, tzinfo=dt.timezone.utc)


class Clock:
    def __init__(self): self.value = NOW
    def now(self): return self.value
    def sleep(self, seconds): self.value += dt.timedelta(seconds=seconds)


class FakeAccount:
    def __init__(self, events):
        self.events = events; self.follows = {}; self.writes = 0
        self.fail_write = False; self.apply_then_fail = False; self.wrong_identity = False
    def identity(self):
        if self.wrong_identity: raise ApiError('wrong_account')
        return {'login': 'anistack72', 'id': 223743812, 'following': len(self.follows)}
    def following(self): return [{'login': n, 'id': i} for n, i in self.follows.items()]
    def observe(self, target): return target in self.follows
    def check_target(self, target, identity): pass
    def mutate(self, verb, target):
        self.events.append(('write', verb, target)); self.writes += 1
        if self.fail_write: raise ApiError('permission_or_restriction_403')
        if verb == 'follow': self.follows[target] = '123'
        else: self.follows.pop(target, None)
        if self.apply_then_fail: raise ApiError('transport_uncertain')


class FakeCheckpoint:
    def __init__(self, events): self.events = events; self.data = None; self.fail = False; self.moved = False
    def guard(self):
        if self.moved: raise ApiError('main_changed')
    def save(self, journal):
        if self.fail: raise ApiError('checkpoint_not_confirmed')
        self.data = copy.deepcopy(export_state(journal)); self.events.append(('checkpoint',))


class Executor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.journal = Journal(Path(self.temp.name) / 'journal.sqlite3')
        self.events = []; self.account = FakeAccount(self.events); self.checkpoint = FakeCheckpoint(self.events); self.clock = Clock()
        self.policy = json.loads((Path(__file__).resolve().parents[1] / 'network-policy.json').read_text())
        self.policy['daily_follow_limit'] = 5
        self.report = {'account': 'anistack72', 'status': 'complete', 'observed_at': NOW.isoformat(),
            'following': [], 'metrics': {'following': 0}, 'candidates': [
              {'login': name, 'id': '123', 'score': 65, 'matching_interests': ['typescript'],
               'recent_public_repo_activity': True, 'bot_signal': 'no_explicit_signal', 'sources': ['tauri-apps/tauri']}
              for name in ['alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot']]}
    def tearDown(self): self.journal.close(); self.temp.cleanup()
    def run_executor(self, apply=True):
        return execute(self.journal, self.account, self.checkpoint, self.report, self.policy,
                       apply=apply, now=self.clock.now, sleep=self.clock.sleep)
    def test_five_relevant_follows_with_durable_reservation_and_spacing(self):
        r = self.run_executor(); self.assertEqual(len(r['confirmed']), 5); self.assertEqual(self.account.writes, 5)
        for i, event in enumerate(self.events):
            if event[0] == 'write': self.assertEqual(self.events[i - 1], ('checkpoint',))
        self.assertGreaterEqual((self.clock.now() - NOW).total_seconds(), 240)
        self.assertEqual(self.run_executor()['confirmed'], []); self.assertEqual(self.account.writes, 5)
    def test_dry_run_never_mutates_or_persists_remote(self):
        self.assertEqual(self.run_executor(False)['status'], 'dry_run'); self.assertEqual(self.events, [])
    def test_failed_checkpoint_prevents_account_mutation(self):
        self.checkpoint.fail = True
        with self.assertRaises(ApiError): self.run_executor()
        self.assertEqual(self.account.writes, 0)
    def test_wrong_account_or_moved_main_prevents_writes(self):
        self.account.wrong_identity = True
        with self.assertRaises(ApiError): self.run_executor()
        self.account.wrong_identity = False; self.checkpoint.moved = True
        with self.assertRaises(ApiError): self.run_executor()
        self.assertEqual(self.account.writes, 0)
    def test_uncertain_write_is_reconciled_without_replay(self):
        self.account.apply_then_fail = True
        with self.assertRaises(ApiError): self.run_executor()
        self.assertEqual(self.account.writes, 1)
        checkpoint = copy.deepcopy(self.checkpoint.data)
        self.journal.close(); self.journal = Journal(Path(self.temp.name) / 'resumed.sqlite3')
        restore_state(self.journal, checkpoint)
        self.policy['daily_follow_limit'] = 1; self.account.apply_then_fail = False
        self.assertEqual(self.run_executor()['confirmed'], []); self.assertEqual(self.account.writes, 1)
        self.assertEqual(self.journal.db.execute("SELECT state FROM network_actions WHERE login='alpha'").fetchone()[0], 'confirmed')
    def test_permission_restriction_suspends_without_retries(self):
        self.account.fail_write = True
        with self.assertRaises(ApiError): self.run_executor()
        self.assertEqual(self.account.writes, 1)
        with self.assertRaises(ApiError): self.run_executor()
        self.assertEqual(self.account.writes, 1)
    def test_explicit_unfollow_works_without_reciprocity_logic(self):
        self.account.follows['removed'] = '456'; self.policy['exclude'] = ['removed']
        self.report['following'] = ['removed']; self.report['metrics']['following'] = 1; self.report['candidates'] = []
        r = self.run_executor(); self.assertEqual(r['confirmed'], [{'verb': 'unfollow', 'login': 'removed', 'verified': True}])
        self.assertEqual(self.account.follows, {})
    def test_screenshot_paths_do_not_enter_cloud_checkpoint(self):
        self.report['candidates'] = self.report['candidates'][:1]; self.run_executor()
        self.journal.db.execute("UPDATE network_actions SET proof='/Users/private/proof.jpg'")
        self.assertNotIn('/Users/', json.dumps(export_state(self.journal)))
    def test_invalid_checkpoint_is_rejected_atomically(self):
        self.run_executor(False); exported = export_state(self.journal)
        exported['actions'][0]['id'] = 'wrong'
        other = Journal(Path(self.temp.name) / 'invalid.sqlite3')
        try:
            with self.assertRaises(ApiError): restore_state(other, exported)
            self.assertEqual(other.db.execute('SELECT count(*) FROM network_actions').fetchone()[0], 0)
        finally: other.close()
    def test_old_discovery_cannot_be_made_fresh_by_live_following_snapshot(self):
        self.report['observed_at'] = (NOW - dt.timedelta(hours=37)).isoformat()
        with self.assertRaises(NetworkError): self.run_executor()
        self.assertEqual(self.account.writes, 0)


class Transport(unittest.TestCase):
    def test_no_write_retry_after_server_error(self):
        calls = []
        def transport(*args): calls.append(args); return 503, {}, b'{}'
        http = Http('not-a-real-credential', 'account', transport=transport, sleep=lambda _: None)
        with self.assertRaises(ApiError): http.request('PUT', '/user/following/alpha')
        self.assertEqual(len(calls), 1)
    def test_read_retries_are_bounded(self):
        calls = []
        def transport(*args): calls.append(args); return 503, {}, b'{}'
        http = Http('not-a-real-credential', 'account', transport=transport, sleep=lambda _: None)
        with self.assertRaises(ApiError): http.request('GET', '/user')
        self.assertEqual(len(calls), 3)
    def test_credentials_cannot_reach_other_origins_or_endpoint_families(self):
        http = Http('not-a-real-credential', 'account', transport=lambda *_: self.fail('network must not run'))
        for method, path in [('GET', 'https://evil.test/user'), ('PUT', STATE_PATH), ('DELETE', '/repos/owner/repo')]:
            with self.assertRaises(ApiError): http.request(method, path)
    def test_follow_uses_empty_body_and_does_not_log_response_content(self):
        calls = []
        def transport(*args): calls.append(args); return 204, {}, b''
        account = Account(Http('not-a-real-credential', 'account', transport=transport))
        account.mutate('follow', 'alpha'); self.assertEqual(calls[0][3], b'')
    def test_checkpoint_writes_are_lease_guarded_and_fixed_to_data_branch(self):
        calls = []
        def transport(method, url, headers, body):
            calls.append((method, url, json.loads(body) if body else None))
            return (200, {}, json.dumps({'sha': 'a'*40} if url.endswith('/commits/main') else {'content': {'sha': 'new-blob'}}).encode())
        state = Checkpoint(Http('not-a-real-credential', 'state', transport=transport), 'a'*40); state.sha = 'expected-blob'
        with tempfile.TemporaryDirectory() as temp:
            journal = Journal(Path(temp)/'state.sqlite3'); state.save(journal); journal.close()
        body = calls[-1][2]; self.assertEqual(body['sha'], 'expected-blob'); self.assertEqual(body['branch'], 'network-data')


if __name__ == '__main__': unittest.main()
