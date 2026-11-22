import base64
import datetime as dt
import hashlib
import json
import re
import urllib.parse

from .api import Deferred


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


def relationships(previous, followers, following):
    def identities(users):
        return {str(user['id']): user['login'] for user in users}
    f, g = identities(followers), identities(following)
    oldf = identities(previous['followers']) if previous else {}
    oldg = identities(previous['following']) if previous else {}
    return {
        'baseline': previous is None,
        'new_followers': [f[k] for k in sorted(f.keys() - oldf.keys())] if previous else [],
        'lost_followers': [oldf[k] for k in sorted(oldf.keys() - f.keys())] if previous else [],
        'you_followed': [g[k] for k in sorted(g.keys() - oldg.keys())] if previous else [],
        'you_unfollowed': [oldg[k] for k in sorted(oldg.keys() - g.keys())] if previous else [],
        'mutual': [f[k] for k in sorted(f.keys() & g.keys())],
        'followers_only': [f[k] for k in sorted(f.keys() - g.keys())],
        'following_only': [g[k] for k in sorted(g.keys() - f.keys())],
        'note': 'Observed snapshot differences; changes between polls and causes are unknown.'
    }


def repository_audit(api, repo):
    full = repo['full_name']
    root = '/repos/' + full
    revision = api.get(root + '/commits/' + urllib.parse.quote(repo['default_branch'], safe=''))
    try:
        commit_sha = revision['sha']
        tree_sha = revision['commit']['tree']['sha']
    except (TypeError, KeyError):
        api.risk.trip('Unexpected commit/tree identity schema')
    tree = api.get(root + '/git/trees/' + tree_sha + '?recursive=1')
    if not isinstance(tree, dict) or not isinstance(tree.get('tree'), list):
        api.risk.trip('Unexpected repository tree schema')
    paths = [node['path'] for node in tree['tree'] if node.get('type') == 'blob']
    lower = [p.lower() for p in paths]
    readme_path = next((p for p in paths if p.lower() in ('readme.md', 'readme.rst', 'readme')), None)
    text = ''
    if readme_path:
        readme = api.get(root + '/contents/' + urllib.parse.quote(readme_path) + '?ref=' + commit_sha)
        if readme.get('encoding') == 'base64':
            try:
                text = base64.b64decode(readme['content'], validate=False).decode('utf-8', errors='replace')
            except (ValueError, KeyError):
                api.risk.trip('Malformed README content')
    checks = {
        'description': bool(repo.get('description')),
        'topics': bool(repo.get('topics')),
        'license': bool(repo.get('license') and repo['license'].get('spdx_id') not in (None, 'NOASSERTION')),
        'readme': bool(text),
        'quickstart': bool(re.search(r'install|quick.?start|getting started|^#{1,3}\s+(run|use)\b', text, re.I | re.M)),
        'example_documented': bool(re.search(r'demo|example|```', text, re.I)),
        'tests_present': any(p.startswith(('tests/', 'test/')) or '/tests/' in p or p.endswith(('.test.ts', '.test.js', '.test.mjs')) for p in lower),
        'ci_present': any(p.startswith('.github/workflows/') for p in lower),
        'security_policy': any(p in ('security.md', '.github/security.md', 'docs/security.md') for p in lower),
        'contributing': any(p.endswith('contributing.md') for p in lower),
        'changelog': any('changelog' in p for p in lower),
    }
    recommendations = [
        {'check': k, 'action': {
            'description': 'Describe the concrete problem and target user in the repository description.',
            'topics': 'Add only accurate technical topics from the implementation.',
            'license': 'Choose and verify a license before encouraging reuse.',
            'readme': 'Document purpose, installation, expected output and limitations.',
            'quickstart': 'Add a reproducible installation and first-run command.',
            'example_documented': 'Provide a reproducible example with expected output.',
            'tests_present': 'Add tests for the documented behavior.',
            'ci_present': 'Run the actual tests as a required CI check.',
            'security_policy': 'Document supported versions and private vulnerability reporting.',
            'contributing': 'Explain development setup and how to submit a useful change.',
            'changelog': 'Record user-visible changes for the next real release.'
        }[k]} for k, ok in checks.items() if not ok]
    score = round(100 * sum(checks.values()) / len(checks))
    return {'repository': full, 'url': repo['html_url'], 'stars': repo['stargazers_count'],
            'language': repo.get('language'), 'topics': repo.get('topics', []),
            'readiness_score': score, 'checks': checks, 'recommendations': recommendations,
            'tree_complete': not tree.get('truncated', False),
            'release_ready': False,
            'release_gate': 'File presence only. Clean-checkout tests, demo, CI and tag verification are required before publishing.',
            'demand': 'unknown; stars and documentation do not establish developer demand',
            'differentiation': 'requires human assessment',
            'tree_sha': tree_sha,
            'commit_sha': commit_sha,
            'forks': repo.get('forks_count', 0),
            'open_issues_and_prs': repo.get('open_issues_count', 0),
            'subscribers': repo.get('subscribers_count'),
            'description': repo.get('description') or full,
            'default_branch': repo['default_branch']}


def discover(api, config, following):
    candidates, opportunities = {}, []
    for seed in config['discovery_seeds']:
        contributors = api.get('/repos/' + seed + '/contributors?per_page=10')
        if not isinstance(contributors, list):
            api.risk.trip('Unexpected contributors schema')
        for user in contributors:
            if user.get('type') != 'User' or user['login'].lower() == config['account'].lower():
                continue
            key = str(user['id'])
            row = candidates.setdefault(key, {'login': user['login'], 'sources': [], 'contributions': 0})
            row['sources'].append(seed)
            row['contributions'] += user.get('contributions', 0)
        issues = api.get('/repos/' + seed + '/issues?labels=good%20first%20issue&state=open&per_page=5')
        if not isinstance(issues, list):
            api.risk.trip('Unexpected issues schema')
        for issue in issues:
            if 'pull_request' not in issue and not issue.get('assignee'):
                opportunities.append({'url': issue['html_url'], 'title': issue['title'],
                                      'repository': seed, 'action': 'Reproduce, read contribution rules, then assess a useful fix.'})
    followed = {str(user['id']) for user in following}
    ranked = sorted(candidates.items(), key=lambda row: (-len(row[1]['sources']), -row[1]['contributions'], row[0]))
    results = []
    interests = {x.lower() for x in config['interests']}
    for identity, candidate in ranked[:config['max_candidates']]:
        user = api.get('/users/' + candidate['login'])
        repos = api.get('/users/' + candidate['login'] + '/repos?sort=pushed&per_page=10')
        signals = set()
        for repo in repos:
            signals.update(t.lower() for t in repo.get('topics', []))
            if repo.get('language'):
                signals.add(repo['language'].lower())
        matches = sorted(interests & signals)
        bot = user.get('type') == 'Bot' or candidate['login'].endswith('[bot]')
        active = any(not r.get('fork') and r.get('pushed_at') and
                     (utcnow() - dt.datetime.fromisoformat(r['pushed_at'].replace('Z', '+00:00'))).days < 180 for r in repos)
        score = min(100, 20 * len(matches) + 10 * len(candidate['sources']) + 15 * active)
        results.append({**candidate, 'id': identity, 'score': 0 if bot else score,
                        'matching_interests': matches, 'recent_public_repo_activity': active,
                        'bot_signal': 'explicit_bot' if bot else 'no_explicit_signal',
                        'quality_assessment': 'heuristic; no identity or intent inference',
                        'already_following': identity in followed,
                        'url': user['html_url'], 'action': 'review_collaboration',
                        'approval': 'required_for_external_interaction'})
    return sorted(results, key=lambda x: (-x['score'], x['login'])), opportunities


def achievement_evidence(api, config, audits, graphql):
    account = config['account']
    q = urllib.parse.quote('author:' + account + ' is:pr is:merged')
    search = api.get('/search/issues?q=' + q + '&per_page=1')
    if not isinstance(search, dict) or 'total_count' not in search or search.get('incomplete_results'):
        api.risk.trip('Incomplete merged-PR search')
    evidence = {'Pull Shark': {'observed_merged_prs': search['total_count'],
                'source': 'https://github.com/search?q=' + q + '&type=pullrequests',
                'caveat': 'Public searchable PRs; usefulness, eligibility exclusions and award require verification.'},
                'Starstruck': {'max_observed_repo_stars': max((r['stars'] for r in audits), default=0),
                              'repositories': {r['repository']: r['stars'] for r in audits}},
                'Quickdraw': {'status': 'unverified', 'next_step': 'Resolve a real issue when its fix is verified; do not create an issue for speed.'},
                'YOLO': {'status': 'unverified', 'next_step': 'Observe normal merges only; never bypass required review to pursue a badge.'},
                'Pair Extraordinaire': {'status': 'unverified', 'next_step': 'Collect commit and merged-PR evidence after real coauthored work.'},
                'Galaxy Brain': {'accepted_answers_in_configured_repos': 0, 'coverage': 'not_collected'},
                'Public Sponsor': {'status': 'unverified', 'requires': 'An actual public sponsorship; no payments are automated.'}}
    if graphql:
        data, _ = api.request('/graphql', query_name='contributions', variables={'login': account})
        user = data['data'].get('user')
        if not user:
            api.risk.trip('GraphQL user not found')
        evidence['contribution_window'] = user['contributionsCollection']
        answers = []
        for full in config['discussion_repositories']:
            owner, name = full.split('/')
            repo = next((r for r in audits if r['repository'] == full), None)
            # Disabled Discussions are not an API failure; explicitly exclude them.
            if not repo or not repo.get('discussions_enabled'):
                continue
            cursor = None
            for _ in range(20):
                data, _ = api.request('/graphql', query_name='discussions', variables={'owner': owner, 'name': name, 'cursor': cursor})
                connection = data['data']['repository']['discussions']
                for node in connection['nodes']:
                    answer = node.get('answer')
                    if answer and (answer.get('author') or {}).get('login', '').lower() == account.lower():
                        answers.append(answer['url'])
                if not connection['pageInfo']['hasNextPage']:
                    break
                cursor = connection['pageInfo']['endCursor']
            else:
                raise Deferred('Discussion pagination bound exceeded')
        evidence['Galaxy Brain'] = {'accepted_answers_in_configured_repos': len(answers),
                                  'evidence_urls': answers, 'coverage': 'configured repositories only'}
    for name in ('Pull Shark', 'Starstruck', 'Quickdraw', 'YOLO', 'Pair Extraordinaire', 'Galaxy Brain', 'Public Sponsor'):
        evidence[name]['award_verified'] = False
        evidence[name]['eligibility'] = 'community-documented; GitHub controls current availability and awards'
    evidence['ineligible'] = ['Arctic Code Vault Contributor', 'Mars 2020 Helicopter Contributor']
    evidence['unknown_unreleased'] = ['Heart On Your Sleeve', 'Open Sourcerer']
    evidence['verification'] = 'Inspect https://github.com/' + account + '?tab=achievements; API evidence does not confirm awards.'
    return evidence


def analytics(history, current):
    now = dt.date.fromisoformat(current['day'])
    cutoff = (now - dt.timedelta(days=7)).isoformat()
    prior = [v for day, v in history if day <= cutoff]
    baseline = prior[-1] if prior else None
    previous = history[-1][1] if history else None
    def change(old):
        if old is None:
            return None
        return {'followers_net': len(current['followers']) - len(old['followers']),
                'repository_stars_net': {r: n - old['stars'][r] if r in old['stars'] else None
                                         for r, n in current['stars'].items()},
                'from': old['day'], 'to': current['day']}
    return {'daily_observed_interval': change(previous), 'weekly_observed_interval': change(baseline),
            'weekly_status': 'available' if baseline else 'insufficient_history',
            'attribution': 'unknown: GitHub does not expose which campaign caused a star or follow',
            'conversion_rate': None, 'conversion_reason': 'No measured unique visitor denominator or campaign attribution.'}


def draft_queue(candidates, opportunities, audits, manual_unfollow):
    queue = []
    for row in candidates:
        if row['score'] >= 30 and not row['already_following'] and row['bot_signal'] != 'explicit_bot':
            queue.append({'operation': 'follow_recommendation', 'target': row['url'],
                          'reason': row['matching_interests'], 'approval': 'pending', 'execute': False})
    # Unfollow is never inferred from failure to follow back or public inactivity.
    for login, reason in manual_unfollow.items():
        if re.fullmatch(r'[A-Za-z0-9-]{1,39}', login) and isinstance(reason, str) and reason.strip():
            queue.append({'operation': 'unfollow_recommendation', 'target': 'https://github.com/' + login,
                          'reason': reason, 'approval': 'pending', 'execute': False})
    for row in audits:
        queue.append({'operation': 'release_announcement_draft', 'repository': row['repository'],
                      'approval': 'pending', 'execute': False,
                      'text': f"{row['repository']}: {row['description']}\nSource and documented examples: {row['url']}\nDraft only: verify tests, demo, release tag and limitations before publishing.",
                      'community_opportunities': [
                          {'url': 'https://github.com/' + row['repository'] + '/releases', 'requirement': 'Publish only a tested, versioned change.'},
                          {'url': 'https://dev.to/new', 'requirement': 'Technical walkthrough; disclose authorship and verify community rules.'},
                          {'url': 'https://news.ycombinator.com/showhn.html', 'requirement': 'Runnable original work; read Show HN rules and engage personally.'}]})
    for item in queue:
        item['id'] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:20]
    return queue
