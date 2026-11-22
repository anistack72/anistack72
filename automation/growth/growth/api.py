import hashlib
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request


class Halt(RuntimeError):
    pass


class Deferred(Halt):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward a credential to a redirect target. Renamed resources need review.
        return None


QUERIES = {
    'contributions': '''query($login:String!){user(login:$login){
      contributionsCollection{startedAt endedAt totalPullRequestContributions
      totalPullRequestReviewContributions totalIssueContributions}
    }rateLimit{remaining resetAt}}''',
    'discussions': '''query($owner:String!,$name:String!,$cursor:String){
      repository(owner:$owner,name:$name){discussions(first:50,after:$cursor){
      nodes{url answer{url author{login}}}pageInfo{hasNextPage endCursor}}}
      rateLimit{remaining resetAt}}''',
}


class RiskController:
    LEVELS = {'read': 'low', 'draft': 'low', 'follow': 'high', 'unfollow': 'high',
              'star': 'high', 'publish': 'high', 'merge': 'critical', 'unknown': 'critical'}

    def __init__(self, state):
        self.state = state

    def authorize(self, operation):
        if self.state.get('suspended'):
            raise Halt('Suspended; inspect state and resolve the cause before manual reset')
        if operation not in ('read', 'draft'):
            raise Halt('External mutations require explicit approval and are not implemented')

    def trip(self, reason):
        self.state.put('suspended', {'reason': reason, 'at': time.time()})
        raise Halt(reason)


class Client:
    BASE = 'https://api.github.com'

    def __init__(self, state, token='', budget=180, reserve=20, transport=None,
                 sleep=time.sleep, clock=time.time):
        self.state, self.risk = state, RiskController(state)
        self.token, self.budget, self.reserve = token, budget, reserve
        self.transport = transport or self._transport
        self.sleep, self.clock = sleep, clock
        self.calls = 0

    @staticmethod
    def _transport(method, url, headers, body):
        req = urllib.request.Request(url, headers=headers, data=body, method=method)
        opener = urllib.request.build_opener(NoRedirect())
        try:
            with opener.open(req, timeout=25) as response:
                return response.status, dict(response.headers), response.read(8_000_001)
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read(8_000_001)

    def request(self, path, query_name=None, variables=None):
        self.risk.authorize('read')
        url = self.BASE + path if path.startswith('/') else path
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme, parsed.netloc) != ('https', 'api.github.com') or parsed.fragment:
            self.risk.trip('Rejected API origin')
        method, body = 'GET', None
        if query_name is not None:
            if path != '/graphql' or query_name not in QUERIES:
                self.risk.trip('Unapproved GraphQL query')
            if not self.token:
                raise Halt('GraphQL requires an authenticated read-only token')
            method = 'POST'
            body = json.dumps({'query': QUERIES[query_name], 'variables': variables or {}}).encode()
        elif parsed.path == '/graphql':
            self.risk.trip('GraphQL requires a fixed query identifier')
        key = hashlib.sha256((url + (body.decode() if body else '')).encode()).hexdigest()
        cached = self.state.cached(key) if method == 'GET' else None
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'anistack72-growth/1.0',
                   'X-GitHub-Api-Version': '2022-11-28'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if body:
            headers['Content-Type'] = 'application/json'
        if cached and cached[0]:
            headers['If-None-Match'] = cached[0]
        for attempt in range(4):
            if self.calls >= self.budget:
                raise Deferred('Per-run request budget exhausted; cache checkpoints preserved')
            until = self.state.get('not_before', 0)
            if until > self.clock():
                raise Deferred('Rate window deferred; retry after stored not_before')
            self.calls += 1
            self.sleep(1.05)  # serialize and bound search API request frequency
            try:
                status, raw_headers, raw = self.transport(method, url, headers, body)
            except (OSError, urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    self.risk.trip('Network retries exhausted')
                self.sleep(min(30, 2 ** attempt) + random.random())
                continue
            h = {k.lower(): v for k, v in raw_headers.items()}
            if len(raw) > 8_000_000:
                self.risk.trip('Oversized API response')
            message = raw.decode('utf-8', errors='replace').lower()
            # Inspect only errors: a README mentioning abuse must not trip the circuit.
            if status >= 400 and any(x in message for x in ('abuse', 'secondary rate', 'temporarily blocked')):
                self.risk.trip('GitHub abuse or secondary-rate warning; manual review required')
            if status in (403, 429) and ('retry-after' in h or h.get('x-ratelimit-remaining') == '0' or status == 429):
                try:
                    until = max(self.clock() + float(h.get('retry-after', '60')),
                                float(h.get('x-ratelimit-reset', '0'))) + random.uniform(1, 5)
                except ValueError:
                    self.risk.trip('Malformed rate-limit headers')
                self.state.put('not_before', until)
                raise Deferred('GitHub rate limit reached; no further requests this run')
            if status in (401, 403):
                self.risk.trip('GitHub authentication/permission failure')
            if 500 <= status <= 599:
                if attempt == 3:
                    self.risk.trip('Server retries exhausted')
                self.sleep(min(30, 2 ** attempt) + random.random())
                continue
            if status == 304:
                if not cached:
                    self.risk.trip('304 without cached representation')
                data, link = json.loads(cached[1]), cached[2]
            elif status == 200:
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    self.risk.trip('Malformed JSON response')
                if method == 'POST' and (not isinstance(data, dict) or data.get('errors') or not data.get('data')):
                    self.risk.trip('GraphQL partial result or error')
                link = h.get('link', '')
                if method == 'GET':
                    self.state.cache(key, h.get('etag'), data, link)
            else:
                self.risk.trip('Unexpected API status ' + str(status))
            if 'x-ratelimit-remaining' in h:
                try:
                    if int(h['x-ratelimit-remaining']) < self.reserve:
                        self.state.put('not_before', max(self.clock() + 60,
                            float(h.get('x-ratelimit-reset', '0'))) + 2)
                except ValueError:
                    self.risk.trip('Malformed rate-limit headers')
            if method == 'POST':
                rate = data['data'].get('rateLimit') or {}
                if rate.get('remaining', self.reserve) < self.reserve:
                    self.state.put('not_before', self.clock() + 3605)
            return data, link
        raise Halt('Unreachable retry state')

    def get(self, path):
        return self.request(path)[0]

    def pages(self, path, max_pages=100):
        results, seen, current = [], set(), path
        for _ in range(max_pages):
            if current in seen:
                self.risk.trip('Pagination loop')
            seen.add(current)
            data, link = self.request(current)
            if not isinstance(data, list):
                self.risk.trip('Expected paginated list')
            results.extend(data)
            match = re.search(r'<([^>]+)>;\s*rel="next"', link or '')
            if not match:
                return results
            current = match.group(1)
        raise Deferred('Pagination bound exceeded; snapshot not committed')
