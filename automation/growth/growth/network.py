"""Bounded account-following queue; external writes are performed by the UI executor.

This module never reads a token or makes a network request. A claim must precede
each UI action; uncertain writes consume their slot until observed, never replayed.
"""
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3

UTC = dt.timezone.utc
LOGIN = re.compile(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,37}[a-zA-Z0-9])?\Z')


class NetworkError(RuntimeError):
    pass


def instant(value):
    stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise NetworkError('Timestamp must include a timezone')
    return stamp.astimezone(UTC)


def login(value):
    if not isinstance(value, str) or not LOGIN.fullmatch(value) or '--' in value:
        raise NetworkError('Invalid GitHub login')
    return value.lower()


def policy_check(policy):
    if policy.get('account') != 'anistack72' or policy.get('schema_version') != 1:
        raise NetworkError('Policy is not authorized for this account')
    for key, maximum in [('daily_follow_limit', 2), ('daily_unfollow_limit', 1),
                         ('following_cap', 50), ('max_report_age_hours', 36)]:
        value = policy.get(key)
        if type(value) is not int or not 1 <= value <= maximum:
            raise NetworkError('Policy exceeds a hard execution bound')
    if not 60 <= policy.get('minimum_interval_seconds', 0) <= 86400:
        raise NetworkError('Invalid mutation interval')
    if not 45 <= policy.get('minimum_score', 0) <= 100:
        raise NetworkError('Invalid relevance threshold')
    if not policy.get('allowed_sources') or any(
            not isinstance(source, str) or not re.fullmatch(r'[\w.-]+/[\w.-]+', source)
            for source in policy['allowed_sources']):
        raise NetworkError('Invalid discovery source')
    for key in ('protected', 'exclude'):
        if not isinstance(policy.get(key), list):
            raise NetworkError('Explicit protected and exclusion lists are required')
        for value in policy[key]:
            login(value)
    if {login(x) for x in policy['protected']} & {login(x) for x in policy['exclude']}:
        raise NetworkError('Protected and excluded accounts overlap; resolve explicitly')
    dt.date.fromisoformat(policy['campaign_end'])


class Journal:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS network_actions(
            id TEXT PRIMARY KEY, verb TEXT NOT NULL, login TEXT NOT NULL,
            state TEXT NOT NULL, planned_at TEXT NOT NULL, started_at TEXT,
            finished_at TEXT, observed TEXT, result TEXT, proof TEXT, proof_sha256 TEXT,
            source TEXT, reason TEXT NOT NULL, UNIQUE(verb,login));
          CREATE TABLE IF NOT EXISTS network_control(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def _check(self, report, policy, now):
        policy_check(policy)
        if now.tzinfo is None:
            raise NetworkError('Execution clock must include a timezone')
        if self.db.execute("SELECT 1 FROM network_control WHERE key='halt'").fetchone():
            raise NetworkError('Network executor is suspended; review the cause before resuming')
        if now.date() > dt.date.fromisoformat(policy['campaign_end']):
            raise NetworkError('Campaign window has ended')
        if report.get('account') != policy['account'] or report.get('status') != 'complete':
            raise NetworkError('A complete report for the authorized account is required')
        age = (now - instant(report['observed_at'])).total_seconds()
        if not -300 <= age <= policy['max_report_age_hours'] * 3600:
            raise NetworkError('Discovery report is stale or dated in the future')

    def _eligible(self, report, policy, now):
        self._check(report, policy, now)
        protected = {login(x) for x in policy['protected']}
        excluded = {login(x) for x in policy['exclude']}
        graph = report['relationships']
        following = {login(x) for x in graph['following_only'] + graph['mutual']}
        if len(following) != report['metrics']['following']:
            raise NetworkError('Following graph is incomplete; do not infer account state')
        rows = list(self.db.execute('SELECT * FROM network_actions'))
        # Incorporate confirmed UI changes newer than the daily analytics checkpoint.
        for row in sorted(rows, key=lambda x: x['finished_at'] or ''):
            if row['result'] in ('changed', 'unchanged') and row['finished_at'] and (
                    instant(row['finished_at']) > instant(report['observed_at'])):
                if row['observed'] == 'following':
                    following.add(row['login'])
                else:
                    following.discard(row['login'])
        completed = {(row['verb'], row['login']) for row in rows if row['state'] != 'planned'}
        ever_removed = {row['login'] for row in rows if row['verb'] == 'unfollow'
                        and row['state'] != 'planned'}
        actions = []
        for target in sorted(excluded & following - protected):
            if target != policy['account'] and ('unfollow', target) not in completed:
                actions.append({'verb': 'unfollow', 'login': target,
                                'reason': 'Explicit policy exclusion; not reciprocity or inactivity'})
        reserved = {row['login'] for row in rows if row['verb'] == 'follow'
                    and row['state'] in ('claimed', 'uncertain')}
        slots = max(0, policy['following_cap'] - len(following | reserved))
        candidates = report.get('candidates', [])
        for row in sorted(candidates, key=lambda r: (-r.get('score', 0), str(r.get('login', '')))):
            target = login(row['login'])
            if target == policy['account'] or target in following | excluded | ever_removed:
                continue
            if ('follow', target) in completed or slots == 0:
                continue
            if (type(row.get('score')) not in (int, float) or row['score'] < policy['minimum_score']
                    or not row.get('matching_interests') or not row.get('recent_public_repo_activity')
                    or row.get('bot_signal') != 'no_explicit_signal'
                    or not str(row.get('id', '')).isdigit()
                    or not set(row.get('sources', [])) & set(policy['allowed_sources'])):
                continue
            if any(a['verb'] == 'follow' and a['login'] == target for a in actions):
                continue
            actions.append({'verb': 'follow', 'login': target,
                            'reason': 'Relevant active contributor: ' + ', '.join(row['sources'])})
            slots -= 1
        return actions

    def plan(self, report, policy, now):
        eligible = self._eligible(report, policy, now)
        actions = []
        for action in eligible:
            identity = hashlib.sha256((policy['account'] + ':' + action['verb'] + ':' + action['login']).encode()).hexdigest()[:24]
            self.db.execute('''INSERT INTO network_actions(id,verb,login,state,planned_at,reason)
               VALUES(?,?,?,'planned',?,?) ON CONFLICT(id) DO UPDATE SET planned_at=excluded.planned_at,
               reason=excluded.reason WHERE network_actions.state='planned' ''',
                            (identity, action['verb'], action['login'], now.isoformat(), action['reason']))
            actions.append({**action, 'id': identity, 'url': 'https://github.com/' + action['login']})
        in_flight = [dict(x) for x in self.db.execute(
            "SELECT id,verb,login,state FROM network_actions WHERE state IN ('claimed','uncertain')")]
        return {'account': policy['account'], 'status': 'planned', 'actions': actions,
                'in_flight': in_flight, 'limits': {'follow': policy['daily_follow_limit'],
                'unfollow': policy['daily_unfollow_limit']},
                'executor': 'Connected GitHub browser session; no external writes performed by planner'}

    def claim(self, identity, report, policy, now):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            eligible = {(x['verb'], x['login']) for x in self._eligible(report, policy, now)}
            row = self.db.execute('SELECT * FROM network_actions WHERE id=?', (identity,)).fetchone()
            if not row or row['state'] != 'planned' or (row['verb'], row['login']) not in eligible:
                raise NetworkError('Action is not currently eligible; never replay an uncertain write')
            today = now.astimezone(UTC).date().isoformat()
            used = self.db.execute('''SELECT count(*) FROM network_actions
                WHERE verb=? AND substr(started_at,1,10)=?''', (row['verb'], today)).fetchone()[0]
            if used >= policy['daily_' + row['verb'] + '_limit']:
                raise NetworkError('Daily action limit reached')
            if self.db.execute("SELECT 1 FROM network_actions WHERE state IN ('claimed','uncertain')").fetchone():
                raise NetworkError('Reconcile the previous action before starting another mutation')
            latest = self.db.execute('''SELECT max(moment) FROM
                (SELECT started_at AS moment FROM network_actions
                 UNION ALL SELECT finished_at AS moment FROM network_actions)''').fetchone()[0]
            if latest and (now - instant(latest)).total_seconds() < policy['minimum_interval_seconds']:
                raise NetworkError('Mutation interval has not elapsed')
            self.db.execute("UPDATE network_actions SET state='claimed', started_at=? WHERE id=?",
                            (now.astimezone(UTC).isoformat(), identity))
            self.db.execute('COMMIT')
            return {'id': identity, 'verb': row['verb'], 'login': row['login'], 'status': 'claimed',
                    'url': 'https://github.com/' + row['login']}
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def finish(self, identity, observed, result, proof, source, now):
        row = self.db.execute('SELECT * FROM network_actions WHERE id=?', (identity,)).fetchone()
        if not row or row['state'] not in ('claimed', 'uncertain'):
            raise NetworkError('Only claimed or uncertain actions may be reconciled')
        expected = 'following' if row['verb'] == 'follow' else 'not_following'
        if result not in ('changed', 'unchanged', 'uncertain') or observed not in ('following', 'not_following', 'unknown'):
            raise NetworkError('Invalid observation')
        if result != 'uncertain' and observed != expected:
            raise NetworkError('Observation does not confirm the intended action')
        if source not in ('https://github.com/' + row['login'],
                          'https://github.com/anistack72?tab=following'):
            raise NetworkError('Proof must identify the target or account following page')
        image = Path(proof)
        if not image.is_file() or image.stat().st_size > 10 * 1024 * 1024:
            raise NetworkError('Proof must be a bounded screenshot file')
        data = image.read_bytes()
        if not data.startswith(b'\xff\xd8') or len(data) < 100:
            raise NetworkError('A real JPEG browser screenshot is required')
        state = 'uncertain' if result == 'uncertain' else 'confirmed'
        self.db.execute('''UPDATE network_actions SET state=?,finished_at=?,observed=?,result=?,proof=?,
            proof_sha256=?,source=? WHERE id=?''', (state, now.isoformat(), observed, result,
            str(Path(proof).resolve()), hashlib.sha256(data).hexdigest(), source, identity))
        return {'id': identity, 'login': row['login'], 'status': state, 'result': result}

    def halt(self):
        self.db.execute("INSERT OR REPLACE INTO network_control VALUES('halt','review_required')")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', default='var/network.sqlite3')
    parser.add_argument('--policy', default='network-policy.json')
    parser.add_argument('--report', default='reports/report.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('plan')
    claim = sub.add_parser('claim'); claim.add_argument('id')
    finish = sub.add_parser('finish'); finish.add_argument('id')
    for key in ('observed', 'result', 'proof', 'source'):
        finish.add_argument('--' + key, required=True)
    sub.add_parser('halt')
    args = parser.parse_args(); journal = Journal(args.state)
    try:
        now = dt.datetime.now(UTC)
        if args.command in ('plan', 'claim'):
            report = json.loads(Path(args.report).read_text()); policy = json.loads(Path(args.policy).read_text())
            result = journal.plan(report, policy, now) if args.command == 'plan' else journal.claim(args.id, report, policy, now)
        elif args.command == 'finish':
            result = journal.finish(args.id, args.observed, args.result, args.proof, args.source, now)
        else:
            journal.halt(); result = {'status': 'suspended'}
        print(json.dumps(result)); return 0
    except (NetworkError, ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        print(json.dumps({'status': 'blocked', 'reason': 'Policy, state, evidence or execution gate rejected the operation'})); return 2
    finally:
        journal.close()


if __name__ == '__main__':
    raise SystemExit(main())
