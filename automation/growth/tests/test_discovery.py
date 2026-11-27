import datetime as dt
import unittest

from growth.intelligence import discover


class Discovery(unittest.TestCase):
    def test_followed_leaders_do_not_starve_new_relevant_candidates(self):
        class API:
            def get(self, path):
                if '/contributors?' in path:
                    self.sample_path = path
                    return [{'id': 1, 'login': 'leader', 'type': 'User', 'contributions': 10000},
                            {'id': 2, 'login': 'peer', 'type': 'User', 'contributions': 20}]
                if '/issues?' in path:
                    return []
                if '/repos?' in path:
                    return [{'language': 'TypeScript', 'topics': [], 'fork': False,
                             'pushed_at': dt.datetime.now(dt.timezone.utc).isoformat()}]
                return {'html_url': 'https://github.com/' + path.split('/')[-1],
                        'type': 'User', 'followers': 50000}
        api = API()
        config = {'account': 'owner', 'discovery_seeds': ['org/project'],
                  'interests': ['typescript'], 'max_candidates': 1}
        rows, _ = discover(api, config, [{'id': 1, 'login': 'leader'}])
        self.assertEqual(rows[0]['login'], 'peer')
        self.assertEqual(api.sample_path, '/repos/org/project/contributors?per_page=30')
        self.assertEqual(rows[0]['audience_followers'], 50000)
        self.assertIsNone(rows[0]['follow_back_probability'])
        self.assertEqual(rows[0]['score'], 45)

    def test_sample_size_bound_prevents_unbounded_discovery(self):
        with self.assertRaises(ValueError):
            discover(None, {'contributor_sample_size': 1000}, [])
