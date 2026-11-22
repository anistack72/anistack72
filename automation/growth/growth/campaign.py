"""Evidence-backed prioritization and a bounded 30-day campaign."""
import datetime as dt

WEIGHTS = {'developer_demand': .30, 'demonstrable_value': .25, 'technical_readiness': .20,
           'discoverability': .15, 'maintenance_quality': .10}


def phase(day, start='2026-11-21', end='2026-12-21'):
    current = dt.date.fromisoformat(day)
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    elapsed = (current - first).days
    if current < first:
        return 'not_started'
    if current > last:
        return 'finished'
    if current == last:
        return 'final_report'
    if elapsed < 3:
        return 'foundation'
    if elapsed < 10:
        return 'launch'
    if elapsed < 20:
        return 'optimization'
    return 'conversion_and_verification'


def rank_repository(row, validations=()):
    checks = row['checks']
    verified = next((v for v in validations if v.get('repository') == row['repository']
                     and v.get('tree') == row.get('tree_sha') and v.get('passed')), None)
    # All scoring is a declared prioritization heuristic, never a predicted growth rate.
    # Demand proxy uses actual received stars and forks, with small explicit caps.
    # Open issue counts include PRs and are not treated as adoption evidence.
    demand = min(100, row['stars'] * 4 + row.get('forks', 0) * 8)
    value = 50 * bool(verified) + 25 * checks['example_documented'] + 25 * checks['readme']
    readiness = 40 * bool(verified) + 20 * checks['tests_present'] + 20 * checks['ci_present'] + 20 * checks['license']
    discovery = sum(25 * checks[k] for k in ('description', 'topics', 'readme', 'quickstart'))
    maintenance = sum(25 * checks[k] for k in ('security_policy', 'contributing', 'changelog', 'ci_present'))
    components = dict(zip(WEIGHTS, (demand, value, readiness, discovery, maintenance)))
    return {'score': round(sum(WEIGHTS[k] * n for k, n in components.items()), 2),
            'weights': WEIGHTS, 'components': components,
            'evidence': {'developer_demand': {'stars': row['stars'], 'forks': row.get('forks', 0),
                         'formula': 'min(100, 4*stars + 8*forks)', 'limitation': 'Sparse popularity proxy; underlying demand unknown.'},
                         'verified_tests_and_demo': verified,
                         'file_presence_checks': checks,
                         'limitations': 'A file-presence check is not proof of execution. Validation applies only to the exact Git tree.'}}


def schedule_tasks(report, start='2026-11-21', end='2026-12-21'):
    current_phase = phase(report['day'], start, end)
    # Adaptive task ordering follows measured gaps; no engagement mutations exist.
    tasks = []
    for row in report['repositories'][:2]:
        for rec in row['recommendations']:
            tasks.append({'kind': 'engineering_recommendation', 'repository': row['repository'],
                          'check': rec['check'], 'action': rec['action'],
                          'priority': round(row['opportunity']['score'] + (25 if rec['check'] in ('quickstart', 'tests_present', 'example_documented') else 10), 2),
                          'risk': 'requires_scoped_implementation', 'status': 'queued'})
    tasks.sort(key=lambda t: (-t['priority'], t['repository'], t['check']))
    return {'phase': current_phase, 'start': start, 'end': end,
            'next_poll_hours': 24 if current_phase not in ('finished', 'not_started') else None,
            'top_two': [r['repository'] for r in report['repositories'][:2]],
            'starstruck_target': {'stars_on_one_repository': 16, 'authority': 'Community-documented threshold; no award guarantee.'},
            'tasks': tasks, 'automatic_executor': ['collect_public_metrics', 'rank_opportunities',
                        'generate_evidence_briefs', 'generate_announcement_drafts', 'persist_checkpoints'],
            'external_publishing': 'No external channel is connected or authorized for posting.'}


def achievement_states(evidence):
    states = {}
    for name in ('Pull Shark', 'Quickdraw', 'YOLO', 'Pair Extraordinaire', 'Galaxy Brain', 'Starstruck', 'Public Sponsor'):
        observed = evidence[name]
        # Availability and criteria are not fully officially specified; community claims
        # never advance REQUIREMENTS_VERIFIED or GITHUB_VERIFIED automatically.
        states[name] = {'state': 'UNKNOWN', 'observed_evidence': observed,
                        'blocked_transition': 'Needs current requirement verification and authoritative award evidence.'}
    return {'transitions': ['UNKNOWN', 'REQUIREMENTS_VERIFIED', 'ELIGIBLE', 'ACTION_COMPLETED', 'GITHUB_VERIFIED'],
            'achievements': states,
            'note': 'Public API evidence is not an award endpoint. A hidden or missing badge is not proof of ineligibility.'}
