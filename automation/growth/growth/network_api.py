"""User-scoped following API executor with durable write-ahead checkpoints.

FOLLOWER_TOKEN never reaches journal data or logs. GITHUB_TOKEN only checkpoints
the fixed network-data branch. Redirects and implicit mutation retries are absent.
"""
import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import time

from .api import Client, Halt
from .intelligence import discover
from .network import Journal, NetworkError, instant, login, policy_check, UTC
from .state import State

REPO = 'anistack72/anistack72'
STATE_PATH = '/repos/' + REPO + '/contents/journal.json'
MAIN_PATH = '/repos/' + REPO + '/commits/main'


class ApiError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Http:
    def __init__(self, token, role, transport=None, sleep=time.sleep):
        if not token or role not in ('account', 'state'):
            raise ApiError('credentials_required')
        self.token, self.role = token, role
        self.transport, self.sleep = transport or Client._transport, sleep
        self.calls = 0

    def request(self, method, path, body=None):
        account_read = method == 'GET' and (
            path == '/user' or re.fullmatch(r'/user/following\?per_page=100&page=[1-5]', path)
            or re.fullmatch(r'/user/following/[A-Za-z0-9-]{1,39}', path)
            or re.fullmatch(r'/users/[A-Za-z0-9-]{1,39}', path))
        account_write = method in ('PUT', 'DELETE') and re.fullmatch(r'/user/following/[A-Za-z0-9-]{1,39}', path)
        state_read = method == 'GET' and path in (STATE_PATH + '?ref=network-data', MAIN_PATH)
        state_write = method == 'PUT' and path == STATE_PATH and isinstance(body, dict) and body.get('branch') == 'network-data'
        if not ((self.role == 'account' and (account_read or account_write))
                or (self.role == 'state' and (state_read or state_write))):
            raise ApiError('endpoint_not_authorized')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'anistack72-network/2',
                   'X-GitHub-Api-Version': '2022-11-28', 'Authorization': 'Bearer ' + self.token}
        payload = json.dumps(body).encode() if body is not None else (b'' if method == 'PUT' else None)
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        # Retry reads only. An uncertain write must be reconciled, never replayed.
        for attempt in range(3 if method == 'GET' else 1):
            if self.calls >= 80:
                raise ApiError('request_budget_exhausted')
            self.calls += 1
            try:
                status, raw_headers, raw = self.transport(method, 'https://api.github.com' + path, headers, payload)
            except (OSError, TimeoutError):
                if method == 'GET' and attempt < 2:
                    self.sleep(2 ** attempt + random.random()); continue
                raise ApiError('transport_uncertain') from None
            if len(raw) > 1024 * 1024:
                raise ApiError('response_too_large')
            if status in (401, 403, 422, 429):
                raise ApiError('permission_or_restriction_' + str(status))
            if 500 <= status < 600:
                if method == 'GET' and attempt < 2:
                    self.sleep(2 ** attempt + random.random()); continue
                raise ApiError('server_uncertain')
            if status not in (200, 201, 204, 404):
                raise ApiError('unexpected_status_' + str(status))
            try:
                data = json.loads(raw) if raw else None
            except (ValueError, UnicodeError):
                raise ApiError('invalid_json') from None
            return status, data
        raise ApiError('read_retries_exhausted')


class Account:
    def __init__(self, http):
        self.http = http

    def identity(self):
        status, user = self.http.request('GET', '/user')
        if status != 200 or not isinstance(user, dict) or user.get('login', '').lower() != 'anistack72' or user.get('id') != 223743812:
            raise ApiError('wrong_account')
        return user

    def following(self):
        rows = []
        for page in range(1, 6):
            status, batch = self.http.request('GET', f'/user/following?per_page=100&page={page}')
            if status != 200 or not isinstance(batch, list):
                raise ApiError('invalid_following_graph')
            rows.extend(batch)
            if len(batch) < 100:
                if len({x['id'] for x in rows}) != len(rows):
                    raise ApiError('changing_following_graph')
                for row in rows:
                    login(row['login'])
                if self.identity()['following'] != len(rows):
                    raise ApiError('changing_following_graph')
                return rows
        raise ApiError('following_graph_bound_exceeded')

    def observe(self, target):
        status, _ = self.http.request('GET', '/user/following/' + login(target))
        if status not in (204, 404):
            raise ApiError('invalid_follow_observation')
        return status == 204

    def check_target(self, target, identity):
        status, user = self.http.request('GET', '/users/' + login(target))
        if status != 200 or not isinstance(user, dict) or user.get('type') != 'User' or str(user.get('id')) != str(identity):
            raise ApiError('target_identity_changed')

    def mutate(self, verb, target):
        if verb not in ('follow', 'unfollow'):
            raise ApiError('invalid_mutation')
        status, _ = self.http.request('PUT' if verb == 'follow' else 'DELETE', '/user/following/' + login(target))
        if status != 204:
            raise ApiError('mutation_not_confirmed')


def export_state(journal):
    actions = []
    for row in journal.db.execute('SELECT * FROM network_actions ORDER BY id'):
        item = dict(row)
        # UI proofs remain local; cloud checkpoints contain public identities only.
        if item['proof'] and item['proof'].startswith('/'):
            item['proof'] = 'local_screenshot_digest:' + (item['proof_sha256'] or '')
        actions.append(item)
    return {'schema_version': 1, 'actions': actions,
            'control': [dict(x) for x in journal.db.execute('SELECT key,value FROM network_control')]}


def restore_state(journal, data):
    if data.get('schema_version') != 1 or not isinstance(data.get('actions'), list) or len(data['actions']) > 5000:
        raise ApiError('invalid_checkpoint')
    if journal.db.execute('SELECT count(*) FROM network_actions').fetchone()[0]:
        raise ApiError('restore_requires_empty_local_journal')
    columns = ('id', 'verb', 'login', 'state', 'planned_at', 'started_at', 'finished_at',
               'observed', 'result', 'proof', 'proof_sha256', 'source', 'reason')
    journal.db.execute('BEGIN IMMEDIATE')
    try:
        for row in data['actions']:
            target = login(row['login']); verb = row['verb']
            identity = hashlib.sha256(('anistack72:' + verb + ':' + target).encode()).hexdigest()[:24]
            if (verb not in ('follow', 'unfollow') or row['id'] != identity
                    or row['login'] != target
                    or row['state'] not in ('planned', 'claimed', 'uncertain', 'confirmed', 'abandoned')):
                raise ApiError('invalid_checkpoint_action')
            if row['observed'] not in (None, 'following', 'not_following', 'unknown') or row['result'] not in (
                    None, 'changed', 'unchanged', 'uncertain', 'reconciled', 'not_applied'):
                raise ApiError('invalid_checkpoint_observation')
            if row['state'] in ('claimed', 'uncertain', 'confirmed', 'abandoned') and not row.get('started_at'):
                raise ApiError('checkpoint_reservation_missing')
            if row.get('source') not in (None, 'https://github.com/' + target,
                                         'https://github.com/anistack72?tab=following'):
                raise ApiError('invalid_checkpoint_source')
            for field in ('planned_at', 'started_at', 'finished_at'):
                if row.get(field): instant(row[field])
            if any(row.get(field) is not None and (not isinstance(row[field], str) or len(row[field]) > 3000)
                   for field in columns):
                raise ApiError('invalid_checkpoint_field')
            journal.db.execute('INSERT INTO network_actions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               tuple(row.get(field) for field in columns))
        for row in data.get('control', []):
            if row != {'key': 'halt', 'value': 'review_required'}:
                raise ApiError('invalid_checkpoint_control')
            journal.db.execute('INSERT INTO network_control VALUES(?,?)', ('halt', 'review_required'))
        journal.db.execute('COMMIT')
    except Exception:
        journal.db.execute('ROLLBACK'); raise


class Checkpoint:
    def __init__(self, http, expected_sha):
        if not re.fullmatch(r'[a-f0-9]{40}', expected_sha): raise ApiError('invalid_source_sha')
        self.http, self.expected_sha, self.sha = http, expected_sha, None

    def guard(self):
        status, commit = self.http.request('GET', MAIN_PATH)
        if status != 200 or commit.get('sha') != self.expected_sha:
            raise ApiError('main_changed')

    def load(self):
        status, obj = self.http.request('GET', STATE_PATH + '?ref=network-data')
        if status != 200 or obj.get('encoding') != 'base64' or obj.get('size', 0) > 512000:
            raise ApiError('checkpoint_missing_or_invalid')
        self.sha = obj['sha']
        return json.loads(base64.b64decode(obj['content']))

    def save(self, journal):
        self.guard()
        encoded = base64.b64encode(json.dumps(export_state(journal), sort_keys=True).encode()).decode()
        if len(encoded) > 700000: raise ApiError('checkpoint_size_bound')
        status, result = self.http.request('PUT', STATE_PATH, {
            'message': 'network: checkpoint verified execution state', 'branch': 'network-data',
            'sha': self.sha, 'content': encoded})
        if status not in (200, 201) or not result.get('content', {}).get('sha'):
            raise ApiError('checkpoint_not_confirmed')
        self.sha = result['content']['sha']


def confirm_api(journal, action, observed, result, now):
    expected = action['verb'] == 'follow'
    if result not in ('changed', 'unchanged', 'reconciled', 'not_applied'):
        raise ApiError('invalid_confirmation')
    if observed != expected and result != 'not_applied':
        raise ApiError('observation_mismatch')
    evidence = json.dumps({'backend': 'GitHub REST', 'read_status': 204 if observed else 404,
                           'target': action['login'], 'checked_at': now.isoformat()}, sort_keys=True)
    changed = journal.db.execute('''UPDATE network_actions SET state=?,finished_at=?,observed=?,result=?,
        proof=?,proof_sha256=?,source=? WHERE id=? AND state IN ('claimed','uncertain')''',
        ('abandoned' if result == 'not_applied' else 'confirmed', now.isoformat(),
         'following' if observed else 'not_following', result, evidence,
         hashlib.sha256(evidence.encode()).hexdigest(), 'https://github.com/' + action['login'], action['id']))
    if changed.rowcount != 1: raise ApiError('confirmation_requires_reservation')


def execute(journal, account, checkpoint, report, policy, apply=False, now=None, sleep=time.sleep):
    now = now or (lambda: dt.datetime.now(UTC))
    policy_check(policy)
    if policy.get('executor_backend') != 'api': raise ApiError('api_backend_disabled')
    account.identity(); checkpoint.guard()
    if journal.db.execute("SELECT 1 FROM network_control WHERE key='halt'").fetchone():
        raise ApiError('executor_suspended')
    if apply:
        for row in list(journal.db.execute("SELECT * FROM network_actions WHERE state IN ('claimed','uncertain')")):
            observed = account.observe(row['login'])
            confirm_api(journal, row, observed, 'reconciled' if observed == (row['verb'] == 'follow') else 'not_applied', now())
            checkpoint.save(journal)
    journal._check(report, policy, now())
    plan = journal.plan(report, policy, now())
    if not apply:
        return {'status': 'dry_run', 'planned': plan['actions']}
    results = []
    candidates = {login(c['login']): c for c in report.get('candidates', [])}
    for action in plan['actions']:
        used = journal.db.execute('SELECT count(*) FROM network_actions WHERE verb=? AND substr(started_at,1,10)=?',
            (action['verb'], now().date().isoformat())).fetchone()[0]
        if used >= policy['daily_' + action['verb'] + '_limit']: continue
        latest = journal.db.execute('''SELECT max(moment) FROM (SELECT started_at AS moment FROM network_actions
            UNION ALL SELECT finished_at AS moment FROM network_actions)''').fetchone()[0]
        delay = max(0, policy['minimum_interval_seconds'] - (now() - instant(latest)).total_seconds()) if latest else 0
        if delay > 65:
            return {'status': 'deferred_cooldown', 'confirmed': results}
        if delay: sleep(delay + 0.1)
        live = account.following()
        current = copy.deepcopy(report)
        current.update(following=[x['login'] for x in live], observed_at=now().isoformat(), metrics={'following': len(live)})
        if action['verb'] == 'follow': account.check_target(action['login'], candidates[action['login']]['id'])
        checkpoint.guard()
        eligible = {(x['verb'], x['login']) for x in journal._eligible(current, policy, now())}
        if (action['verb'], action['login']) not in eligible: continue
        journal.claim(action['id'], current, policy, now())
        checkpoint.save(journal)  # Durable reservation BEFORE touching the account.
        try:
            observed = account.observe(action['login'])
            if observed == (action['verb'] == 'follow'):
                confirm_api(journal, action, observed, 'unchanged', now())
                checkpoint.save(journal); continue
            account.mutate(action['verb'], action['login'])
            observed = account.observe(action['login'])
            if observed != (action['verb'] == 'follow'): raise ApiError('verification_uncertain')
        except ApiError as error:
            journal.db.execute("UPDATE network_actions SET state='uncertain' WHERE id=? AND state='claimed'", (action['id'],))
            if error.code.startswith('permission_or_restriction'): journal.halt()
            checkpoint.save(journal)
            raise
        confirm_api(journal, action, observed, 'changed', now())
        checkpoint.save(journal)
        results.append({'verb': action['verb'], 'login': action['login'], 'verified': True})
    return {'status': 'complete', 'confirmed': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--state', default='var/network-api.sqlite3')
    parser.add_argument('--output', default='var/network-api-report.json')
    args = parser.parse_args()
    journal = None; public_state = None
    try:
        if os.environ.get('GITHUB_REPOSITORY') != REPO: raise ApiError('wrong_repository')
        policy = json.loads(Path('network-policy.json').read_text())
        policy_check(policy)
        if dt.datetime.now(UTC).date() > dt.date.fromisoformat(policy['campaign_end']):
            print(json.dumps({'status': 'campaign_inactive'})); return 0
        account = Account(Http(os.environ.get('FOLLOWER_TOKEN', ''), 'account'))
        checkpoint = Checkpoint(Http(os.environ.get('GITHUB_TOKEN', ''), 'state'), os.environ.get('GITHUB_SHA', ''))
        journal = Journal(args.state); restore_state(journal, checkpoint.load())
        if journal.db.execute("SELECT 1 FROM network_control WHERE key='halt'").fetchone():
            raise ApiError('executor_suspended')
        following = account.following()
        public_state = State('var/network-public-cache.sqlite3')
        config = json.loads(Path('config.json').read_text())
        candidates, _ = discover(Client(public_state, token=os.environ.get('GITHUB_TOKEN', ''), budget=160), config, following)
        report = {'account': 'anistack72', 'status': 'complete', 'observed_at': dt.datetime.now(UTC).isoformat(),
                  'following': [x['login'] for x in following], 'metrics': {'following': len(following)}, 'candidates': candidates}
        result = execute(journal, account, checkpoint, report, policy, args.apply)
        result['backend'] = 'GitHub Actions REST API'; result['account'] = 'anistack72'
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result)); return 0
    except (ApiError, NetworkError, Halt, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        result = {'status': 'blocked', 'reason': error.code if isinstance(error, ApiError) else 'policy_or_state_rejected'}
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result) + '\n')
        print(json.dumps(result)); return 2
    finally:
        if journal: journal.close()
        if public_state: public_state.close()


if __name__ == '__main__':
    raise SystemExit(main())
