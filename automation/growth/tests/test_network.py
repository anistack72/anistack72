import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from growth.network import Journal, NetworkError

NOW = dt.datetime(2026, 11, 24, 18, 0, tzinfo=dt.timezone.utc)


class NetworkGates(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'network.sqlite3'
        self.journal = Journal(self.path)
        self.policy = json.loads((Path(__file__).resolve().parents[1] / 'network-policy.json').read_text())
        self.report = {'account': 'anistack72', 'status': 'complete',
            'observed_at': NOW.isoformat(), 'metrics': {'following': 2},
            'relationships': {'following_only': ['mxyng', 'jberg5'], 'mutual': []},
            'candidates': [self.candidate('alpha'), self.candidate('bravo'), self.candidate('charlie')]}
        self.proof = Path(self.temp.name) / 'proof.jpg'
        self.proof.write_bytes(b'\xff\xd8' + b'fixture' * 30)

    def candidate(self, name):
        return {'login': name, 'id': '123', 'score': 65,
            'matching_interests': ['typescript'], 'recent_public_repo_activity': True,
            'bot_signal': 'no_explicit_signal', 'sources': ['tauri-apps/tauri']}

    def tearDown(self):
        self.journal.close(); self.temp.cleanup()

    def plan(self, now=NOW):
        return self.journal.plan(self.report, self.policy, now)['actions']

    def claim(self, row, now=NOW):
        return self.journal.claim(row['id'], self.report, self.policy, now)

    def finish(self, row, now=NOW, result='changed', observed='following'):
        return self.journal.finish(row['id'], observed, result, str(self.proof),
                                    'https://github.com/' + row['login'], now)

    def test_only_relevant_active_people_are_selected(self):
        for edit in ({'score': 44}, {'matching_interests': []},
                     {'bot_signal': 'explicit_bot'}, {'sources': ['unapproved/repo']},
                     {'recent_public_repo_activity': False}):
            self.report['candidates'] = [{**self.candidate('someone'), **edit}]
            self.assertEqual(self.plan(), [])

    def test_self_and_existing_follows_are_skipped(self):
        self.report['candidates'] = [self.candidate('anistack72'), self.candidate('mxyng')]
        self.assertEqual(self.plan(), [])

    def test_reciprocity_cannot_generate_an_unfollow(self):
        self.report['relationships']['followers_only'] = []
        self.assertFalse(any(a['verb'] == 'unfollow' for a in self.plan()))

    def test_explicit_exclusion_can_unfollow(self):
        self.policy['protected'].remove('jberg5'); self.policy['exclude'] = ['jberg5']
        rows = self.plan(); self.assertEqual(rows[0]['verb'], 'unfollow')
        self.claim(rows[0]); self.finish(rows[0], observed='not_following')
        self.assertFalse(any(a['login'] == 'jberg5' for a in self.plan()))

    def test_protected_exclusion_conflict_fails_closed(self):
        self.policy['exclude'] = ['mxyng']
        with self.assertRaises(NetworkError): self.plan()

    def test_missing_graph_and_wrong_account_fail_closed(self):
        self.report['metrics']['following'] = 3
        with self.assertRaises(NetworkError): self.plan()
        self.report['metrics']['following'] = 2; self.report['account'] = 'someone'
        with self.assertRaises(NetworkError): self.plan()

    def test_stale_future_and_incomplete_reports_are_rejected(self):
        for timestamp in (NOW - dt.timedelta(hours=37), NOW + dt.timedelta(minutes=6)):
            self.report['observed_at'] = timestamp.isoformat()
            with self.assertRaises(NetworkError): self.plan()
        self.report['observed_at'] = NOW.isoformat(); self.report['status'] = 'partial'
        with self.assertRaises(NetworkError): self.plan()

    def test_campaign_cutoff_is_enforced(self):
        self.policy['campaign_end'] = '2026-11-23'
        with self.assertRaises(NetworkError): self.plan()

    def test_daily_budget_is_shared_across_restarts(self):
        rows = self.plan(); self.claim(rows[0])
        self.finish(rows[0])
        self.claim(rows[1], NOW + dt.timedelta(seconds=61))
        self.finish(rows[1], NOW + dt.timedelta(seconds=61))
        other = Journal(self.path)
        try:
            with self.assertRaises(NetworkError):
                other.claim(rows[2]['id'], self.report, self.policy, NOW + dt.timedelta(seconds=122))
        finally: other.close()

    def test_interval_prevents_burst_mutations(self):
        rows = self.plan(); self.claim(rows[0])
        self.finish(rows[0], NOW + dt.timedelta(seconds=30))
        with self.assertRaises(NetworkError): self.claim(rows[1], NOW + dt.timedelta(seconds=61))
        self.claim(rows[1], NOW + dt.timedelta(seconds=91))

    def test_inflight_action_blocks_even_after_interval_elapsed(self):
        rows = self.plan(); self.claim(rows[0])
        with self.assertRaises(NetworkError): self.claim(rows[1], NOW + dt.timedelta(hours=1))

    def test_same_claim_is_not_executed_twice(self):
        row = self.plan()[0]; self.claim(row)
        with self.assertRaises(NetworkError): self.claim(row, NOW + dt.timedelta(seconds=61))

    def test_unconfirmed_actions_reserve_following_capacity(self):
        self.policy['following_cap'] = 3
        row = self.plan()[0]; self.claim(row)
        self.assertEqual(self.plan(NOW + dt.timedelta(seconds=61)), [])

    def test_confirmed_follow_is_not_requeued_on_old_snapshot(self):
        row = self.plan()[0]; self.claim(row); self.finish(row, NOW + dt.timedelta(seconds=1))
        self.assertNotIn(row['id'], [a['id'] for a in self.plan(NOW + dt.timedelta(seconds=61))])

    def test_removal_is_not_reversed_after_policy_changes(self):
        self.report['relationships']['following_only'] = ['alpha', 'jberg5']
        self.policy['exclude'] = ['alpha']; row = self.plan()[0]
        self.claim(row); self.finish(row, NOW + dt.timedelta(seconds=1), observed='not_following')
        self.policy['exclude'] = []
        self.assertFalse(any(a['login'] == 'alpha' for a in self.plan(NOW + dt.timedelta(seconds=61))))

    def test_changed_policy_invalidates_queued_actions(self):
        row = self.plan()[0]; self.policy['exclude'] = [row['login']]
        with self.assertRaises(NetworkError): self.claim(row)

    def test_uncertain_result_requires_observation_not_reexecution(self):
        row = self.plan()[0]; self.claim(row)
        self.finish(row, result='uncertain', observed='unknown')
        with self.assertRaises(NetworkError): self.claim(row, NOW + dt.timedelta(seconds=61))
        self.finish(row, NOW + dt.timedelta(seconds=61))
        self.assertNotIn(row['id'], [a['id'] for a in self.plan(NOW + dt.timedelta(seconds=122))])

    def test_missing_or_wrong_proof_cannot_confirm_an_action(self):
        row = self.plan()[0]; self.claim(row)
        with self.assertRaises(NetworkError): self.finish(row, observed='not_following')
        self.proof.write_text('not an image')
        with self.assertRaises(NetworkError): self.finish(row)

    def test_suspension_is_persistent(self):
        self.journal.halt()
        other = Journal(self.path)
        try:
            with self.assertRaises(NetworkError): other.plan(self.report, self.policy, NOW)
        finally: other.close()

    def test_malformed_target_or_unsafe_limits_are_rejected(self):
        self.report['candidates'][0]['login'] = '../user'
        with self.assertRaises(NetworkError): self.plan()
        self.report['candidates'][0]['login'] = 'alpha'; self.policy['daily_follow_limit'] = 1000
        with self.assertRaises(NetworkError): self.plan()

    def test_planning_does_not_mutate_the_discovery_report(self):
        before = copy.deepcopy(self.report); self.plan(); self.assertEqual(before, self.report)


if __name__ == '__main__':
    unittest.main()
