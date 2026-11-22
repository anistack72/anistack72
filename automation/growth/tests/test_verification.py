import unittest
from growth.verification import inspect_profile_html, verify_profile


def badge(account='owner', slug='pull-shark', name='Pull Shark'):
    return f'''<html><a href="/{account}?achievement={slug}&amp;tab=achievements">
      <img src="https://github.githubassets.com/assets/{slug}-default.png"
       data-hovercard-type="achievement" data-hovercard-url="/users/{account}/achievements/{slug}/detail?hovercard=1"
       alt="Achievement: {name}" class="achievement-badge-sidebar" /></a></html>'''


class Verification(unittest.TestCase):
    def test_visible_github_badge_is_recorded_with_evidence(self):
        results = inspect_profile_html('owner', badge())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['name'], 'Pull Shark')
        self.assertTrue(results[0]['github_award_url'].startswith('https://github.com/owner?'))

    def test_other_account_badge_is_rejected(self):
        self.assertEqual(inspect_profile_html('owner', badge('other')), [])

    def test_untrusted_asset_and_wrong_label_are_rejected(self):
        self.assertEqual(inspect_profile_html('owner', badge().replace('github.githubassets.com', 'evil.invalid')), [])
        self.assertEqual(inspect_profile_html('owner', badge(name='Fake Badge')), [])

    def test_readme_image_is_not_an_award(self):
        self.assertEqual(inspect_profile_html('owner', '<html><img alt="Achievement: Pull Shark" src="https://github.githubassets.com/assets/pull-shark.png"></html>'), [])

    def test_no_badge_is_unknown_not_a_revocation(self):
        result = verify_profile('owner', fetch=lambda _: b'<html><title>Profile</title></html>')
        self.assertEqual(result['status'], 'no_visible_badges_observed')
        self.assertEqual(result['badges'], [])

    def test_unavailable_and_malformed_profile_never_verify(self):
        def unavailable(_):
            raise OSError('do not log this arbitrary text')
        self.assertEqual(verify_profile('owner', fetch=unavailable)['status'], 'unavailable')
        self.assertEqual(verify_profile('owner', fetch=lambda _: b'not HTML')['status'], 'unavailable')

    def test_duplicate_rendering_does_not_duplicate_awards(self):
        self.assertEqual(len(inspect_profile_html('owner', badge() + badge())), 1)
