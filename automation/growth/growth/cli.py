import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from .api import Client, Halt, Deferred
from .intelligence import (utcnow, relationships, repository_audit, discover,
                           achievement_evidence, analytics, draft_queue)
from .state import State
from .campaign import rank_repository, schedule_tasks, achievement_states, phase
from .verification import verify_profile


def log(event, **fields):
    print(json.dumps({'at': utcnow().isoformat(), 'event': event, **fields}), flush=True)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
        temporary = handle.name
    os.replace(temporary, path)


def run(api, state, config, output, discovery=True, graphql=True):
    day = utcnow().date().isoformat()
    history = state.history()
    if history and history[-1][0] == day:
        cached = state.get('latest_report')
        if cached:
            atomic_json(Path(output) / 'report.json', cached)
        log('unchanged', day=day, reason='complete_daily_checkpoint_exists')
        return cached
    account = config['account']
    profile = api.get('/users/' + account)
    followers = api.pages('/users/' + account + '/followers?per_page=100')
    following = api.pages('/users/' + account + '/following?per_page=100')
    for users in (followers, following):
        if any(not isinstance(x, dict) or not x.get('id') or not x.get('login') for x in users):
            api.risk.trip('Unexpected relationship schema')
        if len({x['id'] for x in users}) != len(users):
            api.risk.trip('Duplicate IDs during graph pagination; recollect after review')
    # Counts are re-read to detect moving or truncated collections, including equal-count changes only partially detectable.
    final_profile = api.get('/users/' + account)
    if (len(followers), len(following)) != (final_profile['followers'], final_profile['following']):
        api.risk.trip('Relationship counts changed during collection or pagination incomplete')
    old = history[-1][1] if history else None
    if old and len(old['followers']) >= 20 and len(followers) < len(old['followers']) / 2:
        api.risk.trip('Follower drop exceeds anomaly threshold; preserve previous baseline')
    repos = api.pages('/users/' + account + '/repos?per_page=100&type=owner&sort=full_name')
    owned = [r for r in repos if r['owner']['login'].lower() == account.lower()
             and not r['fork'] and not r['archived'] and not r['private']]
    audits = []
    for repo in owned:
        audit = repository_audit(api, repo)
        audit['discussions_enabled'] = repo.get('has_discussions', False)
        audits.append(audit)
    validation_path = Path(__file__).resolve().parent.parent / 'evidence' / 'repository-validation.json'
    validations = json.loads(validation_path.read_text()) if validation_path.exists() else []
    for audit in audits:
        audit['opportunity'] = rank_repository(audit, validations)
    audits.sort(key=lambda row: (-row['opportunity']['score'], -row['stars'], row['repository']))
    candidates, opportunities = discover(api, config, following) if discovery else ([], [])
    achievements = achievement_evidence(api, config, audits, graphql and bool(api.token))
    profile_verification = verify_profile(account)
    for badge in profile_verification['badges']:
        if badge['name'] in achievements:
            achievements[badge['name']]['award_verified'] = True
            achievements[badge['name']]['visible_award_evidence'] = {**badge, 'checked_at': profile_verification['checked_at']}
    snapshot = {'day': day, 'observed_at': utcnow().isoformat(),
                'followers': [{'id': u['id'], 'login': u['login']} for u in followers],
                'following': [{'id': u['id'], 'login': u['login']} for u in following],
                'stars': {r['full_name']: r['stargazers_count'] for r in owned}}
    report = {'schema_version': 1, 'account': account, 'day': day,
              'observed_at': snapshot['observed_at'], 'status': 'complete',
              'metrics': {'followers': len(followers), 'following': len(following),
                          'stars_received_owned_active_public': sum(snapshot['stars'].values())},
              'relationships': relationships(old, followers, following),
              'repositories': audits, 'candidates': candidates, 'opportunities': opportunities,
              'queue': draft_queue(candidates, opportunities, audits, config.get('unfollow_review', {})),
              'achievements': achievements, 'analytics': analytics(history, snapshot),
              'capabilities': {'discovery': discovery, 'graphql': graphql and bool(api.token),
                               'visible_badge_verification': True,
                               'external_mutations': False, 'release_publish': False},
              'requests': api.calls}
    report['profile_verification'] = profile_verification
    report['campaign'] = schedule_tasks(report, config.get('campaign_start', '2026-11-21'), config.get('campaign_end', '2026-12-21'))
    report['achievement_states'] = achievement_states(achievements)
    # Commit snapshot and report together. Export can be recovered idempotently on rerun.
    with state.db:
        state.db.execute('INSERT INTO snapshots VALUES (?,?)', (day, json.dumps(snapshot)))
        state.db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('latest_report', json.dumps(report)))
        state.db.execute('DELETE FROM snapshots WHERE day < date(?, "-90 days")', (day,))
    atomic_json(Path(output) / 'report.json', report)
    write_brief(output, report)
    log('complete', day=day, metrics=report['metrics'], requests=api.calls)
    return report


def write_brief(output, report):
    lines = [f"# Growth intelligence — {report['day']}", '',
             'Observed public data; no campaign or badge award attribution.', '',
             '| Repository | Opportunity heuristic | Stars |', '|---|---:|---:|']
    for row in report['repositories']:
        lines.append(f"| {row['repository']} | {row['opportunity']['score']}/100 | {row['stars']} |")
    lines.extend(['', '## Useful next work', ''])
    for row in report['repositories'][:3]:
        for rec in row['recommendations'][:2]:
            lines.append(f"- {row['repository']}: {rec['action']}")
    lines.extend(['', '## Collaboration opportunities', ''])
    for opportunity in report['opportunities']:
        lines.append(f"- {opportunity['url']}")
    lines.extend(['', 'All interaction and release drafts remain pending. No automatic follow, star, merge or external posting.', ''])
    Path(output).mkdir(parents=True, exist_ok=True)
    (Path(output) / 'brief.md').write_text('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(description='Read-only GitHub growth intelligence')
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--state', default='var/state.sqlite3')
    parser.add_argument('--output', default='var/reports')
    parser.add_argument('--dry-run', action='store_true', help='Live GET/query reads; disposable copy of persistent state')
    parser.add_argument('--no-discovery', action='store_true')
    parser.add_argument('--no-graphql', action='store_true')
    parser.add_argument('--budget', type=int)
    parser.add_argument('--resume-after-review', action='store_true', help='Clear suspension after operator resolves documented cause')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if phase(utcnow().date().isoformat(), config.get('campaign_start', '2026-11-21'), config.get('campaign_end', '2026-12-21')) in ('finished', 'not_started'):
        log('campaign_inactive')
        return 0
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', config['account']):
        parser.error('Invalid account')
    for full in config['discovery_seeds'] + config['discussion_repositories']:
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', full):
            parser.error('Invalid repository')
    if not 0 <= config['max_candidates'] <= 30:
        parser.error('Candidate budget must be between 0 and 30')
    temp = tempfile.TemporaryDirectory() if args.dry_run else None
    path = args.state
    if temp:
        path = str(Path(temp.name) / 'state.sqlite3')
        if Path(args.state).exists():
            shutil.copy2(args.state, path)
    state = State(path)
    try:
        with state.lock():
            if args.resume_after_review:
                state.put('suspended', None)
                log('operator_reset', reason='explicit_local_cli_flag')
            api = Client(state, os.environ.get('GITHUB_TOKEN', ''),
                         budget=args.budget if args.budget is not None else config['request_budget'],
                         reserve=config['reserve'])
            api.risk.authorize('read')
            report = run(api, state, config, args.output, not args.no_discovery, not args.no_graphql)
            if report:
                write_brief(args.output, report)
    except Deferred as error:
        log('deferred', reason=str(error))
        return 75
    except Halt as error:
        log('halted', reason=str(error))
        return 2
    except Exception as error:
        # Never log API bodies, headers, tokens or arbitrary exception strings.
        state.put('suspended', {'reason': 'Unexpected collector exception', 'type': type(error).__name__})
        log('failed', error_type=type(error).__name__)
        return 2
    finally:
        state.close()
        if temp:
            temp.cleanup()
    return 0


if __name__ == '__main__':
    sys.exit(main())
