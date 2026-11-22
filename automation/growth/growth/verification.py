"""Credential-free observation of badges actually rendered by GitHub's public UI."""
import datetime as dt
from html.parser import HTMLParser
import re
import urllib.error
import urllib.parse
import urllib.request

from .api import NoRedirect

BADGES = {'pull-shark': 'Pull Shark', 'quickdraw': 'Quickdraw', 'yolo': 'YOLO',
          'pair-extraordinaire': 'Pair Extraordinaire', 'galaxy-brain': 'Galaxy Brain',
          'starstruck': 'Starstruck', 'public-sponsor': 'Public Sponsor'}


class BadgeParser(HTMLParser):
    def __init__(self, account):
        super().__init__()
        self.account = account.lower()
        self.anchor = None
        self.badges = {}

    def handle_starttag(self, tag, attributes):
        a = dict(attributes)
        if tag == 'a':
            self.anchor = None
            parsed = urllib.parse.urlsplit(a.get('href') or '')
            query = urllib.parse.parse_qs(parsed.query)
            slug = query.get('achievement', [None])[0]
            if (not parsed.netloc and parsed.path.lower() == '/' + self.account
                    and slug in BADGES and query.get('tab') == ['achievements']):
                self.anchor = (slug, a['href'])
        if tag == 'img' and self.anchor:
            slug, href = self.anchor
            expected = 'Achievement: ' + BADGES[slug]
            source = urllib.parse.urlsplit(a.get('src') or '')
            hover = urllib.parse.urlsplit(a.get('data-hovercard-url') or '')
            if ('achievement-badge-sidebar' in (a.get('class') or '').split()
                    and a.get('data-hovercard-type') == 'achievement'
                    and a.get('alt') == expected
                    and source.scheme == 'https' and source.netloc == 'github.githubassets.com'
                    and hover.path.lower() == f'/users/{self.account}/achievements/{slug}/detail'):
                self.badges[BADGES[slug]] = {'name': BADGES[slug], 'slug': slug,
                    'github_award_url': 'https://github.com' + href,
                    'captured_evidence': {'alt': expected, 'image_url': a['src'],
                        'hovercard_path': a['data-hovercard-url'], 'selector': 'img.achievement-badge-sidebar'},
                    'authority': 'Badge actually rendered on GitHub public profile; tier not inferred.'}

    def handle_endtag(self, tag):
        if tag == 'a':
            self.anchor = None


def inspect_profile_html(account, html):
    parser = BadgeParser(account)
    parser.feed(html)
    return list(parser.badges.values())


def verify_profile(account, fetch=None):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', account):
        raise ValueError('Invalid profile account')
    url = 'https://github.com/' + account
    observed = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        if fetch:
            raw = fetch(url)
        else:
            request = urllib.request.Request(url, headers={'User-Agent': 'anistack72-growth/1.0', 'Accept': 'text/html'})
            opener = urllib.request.build_opener(NoRedirect())
            with opener.open(request, timeout=20) as response:
                raw = response.read(3_000_001)
        if len(raw) > 3_000_000:
            return {'status': 'unavailable', 'reason': 'oversized_profile', 'url': url, 'checked_at': observed, 'badges': []}
        html = raw.decode('utf-8')
        if '<html' not in html.lower():
            return {'status': 'unavailable', 'reason': 'unexpected_profile_response', 'url': url, 'checked_at': observed, 'badges': []}
        badges = inspect_profile_html(account, html)
        return {'status': 'visible_badges_observed' if badges else 'no_visible_badges_observed',
                'url': url, 'checked_at': observed, 'badges': badges,
                'limitation': 'Public UI only. Absence does not prove no award; private/hidden badges and UI changes remain unknown.'}
    except (OSError, UnicodeError, urllib.error.URLError):
        return {'status': 'unavailable', 'url': url, 'checked_at': observed, 'badges': [],
                'reason': 'Public profile unavailable; no award inferred and no immediate retry.'}
