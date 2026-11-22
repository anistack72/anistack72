import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from growth.api import Client, Deferred, Halt, RiskController
from growth.campaign import phase, rank_repository, schedule_tasks, achievement_states, transition_achievement
from growth.cli import run
from growth.intelligence import relationships, analytics, draft_queue, repository_audit
from growth.state import State


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.state = State(Path(self.temp.name) / 'state.sqlite3')

    def tearDown(self):
        self.state.close()
        self.temp.cleanup()

    def client(self, responses, **kwargs):
        self.seen = []
        def transport(method, url, headers, body):
            self.seen.append((method, url, headers, body))
            return responses.pop(0)
        return Client(self.state, transport=transport, sleep=lambda _: None, **kwargs)


def response(data, headers=None, status=200):
    return status, headers or {}, json.dumps(data).encode()


class API(Base):
    def test_cache_304_reuses_representation_and_link(self):
        client = self.client([response([{'id': 1}], {'ETag': '"abc"', 'Link': '<https://api.github.com/users/x/followers?page=2>; rel="next"'}), (304, {}, b'')])
        first = client.request('/users/x/followers')
        self.assertEqual(client.request('/users/x/followers'), first)
        self.assertEqual(self.seen[1][2]['If-None-Match'], '"abc"')

    def test_paginated_collection_uses_next_link(self):
        client = self.client([response([{'id': 1}], {'Link': '<https://api.github.com/users/x/followers?page=2>; rel="next"'}), response([{'id': 2}])])
        self.assertEqual([r['id'] for r in client.pages('/users/x/followers')], [1, 2])

    def test_external_next_link_never_receives_token(self):
        client = self.client([response([], {'Link': '<https://evil.example/>; rel="next"'})], token='secret')
        with self.assertRaises(Halt):
            client.pages('/users/x/followers')
        self.assertEqual(len(self.seen), 1)

    def test_unapproved_graphql_never_executes(self):
        client = self.client([], token='secret')
        with self.assertRaises(Halt):
            client.request('/graphql', query_name='mutation')
        self.assertEqual(self.seen, [])

    def test_fixed_graphql_query_is_read_only(self):
        client = self.client([response({'data': {'user': {}}})], token='secret')
        client.request('/graphql', query_name='contributions', variables={'login': 'x'})
        payload = json.loads(self.seen[0][3])
        self.assertTrue(payload['query'].startswith('query('))
        self.assertNotIn('mutation', payload['query'])

    def test_graphql_partial_errors_trip_circuit(self):
        client = self.client([response({'data': {'user': {}}, 'errors': [{'message': 'Denied'}]})], token='secret')
        with self.assertRaises(Halt):
            client.request('/graphql', query_name='contributions')
        self.assertTrue(self.state.get('suspended'))

    def test_permission_failures_persist_suspension(self):
        for status in (401, 403):
            self.state.put('suspended', None)
            client = self.client([response({'message': 'denied'}, status=status)])
            with self.assertRaises(Halt):
                client.get('/users/x')
            with self.assertRaises(Halt):
                client.get('/users/x')
            self.assertEqual(len(self.seen), 1)

    def test_rate_limit_defers_without_sleeping_until_reset(self):
        client = self.client([response({'message': 'API rate limit exceeded'}, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '5000'}, 403)], clock=lambda: 1000)
        with self.assertRaises(Deferred):
            client.get('/users/x')
        self.assertGreater(self.state.get('not_before'), 5000)
        self.assertFalse(self.state.get('suspended'))
        with self.assertRaises(Deferred):
            client.get('/users/x')
        self.assertEqual(len(self.seen), 1)

    def test_secondary_abuse_warning_trips(self):
        client = self.client([response({'message': 'You have exceeded a secondary rate limit'}, status=403)])
        with self.assertRaises(Halt):
            client.get('/users/x')
        self.assertTrue(self.state.get('suspended'))

    def test_readme_discussing_abuse_does_not_trip(self):
        self.client([response({'text': 'abuse prevention'})]).get('/repos/x/y/contents/README.md')
        self.assertFalse(self.state.get('suspended'))

    def test_transient_failure_retries_bounded(self):
        client = self.client([response({}, status=503), response({'id': 1})])
        self.assertEqual(client.get('/users/x'), {'id': 1})
        self.assertEqual(client.calls, 2)

    def test_exhausted_retries_trip(self):
        client = self.client([response({}, status=503)] * 4)
        with self.assertRaises(Halt):
            client.get('/users/x')
        self.assertEqual(client.calls, 4)

    def test_malformed_json_trips(self):
        client = self.client([(200, {}, b'<html>invalid</html>')])
        with self.assertRaises(Halt):
            client.get('/users/x')

    def test_redirect_rejected(self):
        client = self.client([(302, {'Location': 'https://evil.example'}, b'')])
        with self.assertRaises(Halt):
            client.get('/users/x')

    def test_budget_preserves_cache(self):
        client = self.client([response({'id': 1})], budget=1)
        client.get('/users/x')
        with self.assertRaises(Deferred):
            client.get('/users/y')
        self.assertEqual(self.state.db.execute('SELECT count(*) FROM cache').fetchone()[0], 1)

    def test_pagination_limit_never_returns_partial(self):
        client = self.client([response([], {'Link': '<https://api.github.com/users/x/followers?page=2>; rel="next"'})])
        with self.assertRaises(Deferred):
            client.pages('/users/x/followers', max_pages=1)

    def test_mutations_denied_even_with_token(self):
        for op in ('follow', 'unfollow', 'star', 'publish', 'merge', 'something_new'):
            with self.assertRaises(Halt):
                RiskController(self.state).authorize(op)


class Logic(Base):
    def test_award_state_cannot_skip_evidence_or_infer_from_a_threshold(self):
        with self.assertRaises(ValueError):
            transition_achievement('UNKNOWN', 'GITHUB_VERIFIED', {'stars': 16})
        with self.assertRaises(ValueError):
            transition_achievement('ACTION_COMPLETED', 'GITHUB_VERIFIED', {'checked_at': '2026-11-23', 'stars': 16})

    def test_action_transition_rejects_fabricated_work(self):
        with self.assertRaises(ValueError):
            transition_achievement('ELIGIBLE', 'ACTION_COMPLETED', {'checked_at': '2026-11-23', 'event_urls': ['https://github.com/x/y/pull/1'], 'useful_work_verified': True, 'fabricated': True})

    def test_requirement_transition_records_evidence(self):
        evidence = {'checked_at': '2026-11-23', 'requirements_source': 'https://github.com/Schweinepriester/github-profile-achievements', 'criteria_reviewed': True}
        self.assertEqual(transition_achievement('UNKNOWN', 'REQUIREMENTS_VERIFIED', evidence)['state'], 'REQUIREMENTS_VERIFIED')

    def test_baseline_does_not_invent_gains(self):
        result = relationships(None, [{'id': 1, 'login': 'a'}], [])
        self.assertTrue(result['baseline'])
        self.assertEqual(result['new_followers'], [])

    def test_rename_is_not_follower_loss(self):
        result = relationships({'followers': [{'id': 1, 'login': 'old'}], 'following': []}, [{'id': 1, 'login': 'new'}], [])
        self.assertEqual(result['new_followers'], [])
        self.assertEqual(result['lost_followers'], [])

    def test_mutual_and_changes(self):
        old = {'followers': [{'id': 1, 'login': 'a'}], 'following': []}
        users = [{'id': 2, 'login': 'b'}]
        result = relationships(old, users, users)
        self.assertEqual(result['mutual'], ['b'])
        self.assertEqual(result['new_followers'], ['b'])
        self.assertEqual(result['lost_followers'], ['a'])

    def test_weekly_does_not_invent_baseline(self):
        current = {'day': '2026-11-23', 'followers': [], 'stars': {'x/y': 3}}
        self.assertIsNone(analytics([], current)['weekly_observed_interval'])
        self.assertIsNone(analytics([], current)['conversion_rate'])

    def test_weekly_uses_actual_older_snapshot(self):
        old = {'day': '2026-11-21', 'followers': [1], 'stars': {'x/y': 3}}
        current = {'day': '2026-11-29', 'followers': [1, 2], 'stars': {'x/y': 5, 'x/new': 1}}
        result = analytics([('2026-11-21', old)], current)['weekly_observed_interval']
        self.assertEqual(result['followers_net'], 1)
        self.assertEqual(result['repository_stars_net']['x/y'], 2)
        self.assertIsNone(result['repository_stars_net']['x/new'])

    def test_queue_is_deterministic_and_never_executes(self):
        rows = [{'repository': 'x/y', 'description': 'A tool', 'url': 'https://github.com/x/y'}]
        queue = draft_queue([], [], rows, {'real': 'No longer relevant'})
        self.assertEqual(queue, draft_queue([], [], rows, {'real': 'No longer relevant'}))
        self.assertTrue(all(x['execute'] is False for x in queue))

    def test_campaign_end_and_phases(self):
        self.assertEqual(phase('2026-11-23'), 'foundation')
        self.assertEqual(phase('2026-12-21'), 'final_report')
        self.assertEqual(phase('2026-12-22'), 'finished')

    def test_ranking_evidence_must_match_tree(self):
        checks = dict.fromkeys(('description', 'topics', 'readme', 'quickstart', 'example_documented', 'tests_present', 'ci_present', 'license', 'security_policy', 'contributing', 'changelog'), True)
        row = {'repository': 'x/y', 'tree_sha': 'a', 'stars': 0, 'checks': checks}
        old = [{'repository': 'x/y', 'tree': 'b', 'passed': True}]
        verified = [{'repository': 'x/y', 'tree': 'a', 'passed': True}]
        score = rank_repository(row, old)
        self.assertEqual(score['components']['developer_demand'], 0)
        self.assertIsNone(score['evidence']['verified_tests_and_demo'])
        self.assertGreater(rank_repository(row, verified)['score'], score['score'])

    def test_process_lock_excludes_another_connection(self):
        other = State(self.state.path)
        try:
            with self.state.lock():
                with self.assertRaises(RuntimeError):
                    with other.lock():
                        pass
        finally:
            other.close()


class Integration(Base):
    def test_repository_audit_pins_tree_and_readme_to_same_commit(self):
        api = self.client([
            response({'sha': 'commit123', 'commit': {'tree': {'sha': 'tree456'}}}),
            response({'sha': 'tree456', 'tree': [{'path': 'README.md', 'type': 'blob'}]}),
            response({'encoding': 'base64', 'content': 'IyBSdW4K'}),
        ])
        audit = repository_audit(api, {'full_name': 'x/y', 'default_branch': 'main',
                                      'html_url': 'https://github.com/x/y', 'stargazers_count': 0})
        self.assertEqual(audit['tree_sha'], 'tree456')
        self.assertEqual(audit['commit_sha'], 'commit123')
        self.assertTrue(self.seen[1][1].endswith('/git/trees/tree456?recursive=1'))
        self.assertTrue(self.seen[2][1].endswith('?ref=commit123'))

    def test_complete_run_is_atomic_and_idempotent(self):
        api = self.client([response({'followers': 0, 'following': 0}), response([]), response([]),
                           response({'followers': 0, 'following': 0}), response([]), response({'total_count': 0})])
        config = {'account': 'owner', 'discovery_seeds': [], 'discussion_repositories': []}
        first = run(api, self.state, config, self.temp.name, discovery=False, graphql=False)
        calls = api.calls
        second = run(api, self.state, config, self.temp.name, discovery=False, graphql=False)
        self.assertEqual(api.calls, calls)
        self.assertEqual(first, second)
        self.assertEqual(len(self.state.history()), 1)
        self.assertEqual(first['metrics']['followers'], 0)
        self.assertFalse(first['achievements']['Starstruck']['award_verified'])

    def test_partial_graph_never_committed(self):
        api = self.client([response({'followers': 1, 'following': 0}), response([]), response([]),
                           response({'followers': 1, 'following': 0})])
        with self.assertRaises(Halt):
            run(api, self.state, {'account': 'owner'}, self.temp.name, discovery=False, graphql=False)
        self.assertEqual(self.state.history(), [])
        self.assertIsNone(self.state.get('latest_report'))


if __name__ == '__main__':
    unittest.main()
