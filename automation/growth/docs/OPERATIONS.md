# Operations, monitoring and recovery

## Deployment contract

Install the package under `automation/growth/` without changing existing files. Install `growth-ci.yml` and `growth-campaign.yml` in the root workflow directory. Use a normal fast-forward commit from the inspected current head. Never force-push, merge the separate profile PR, relax protections or enlarge token permissions to make a failed deployment pass.

Collector job: repository `contents: read`. Persistence job: `contents: write` only for pushing generated files onto **growth-data**. The latter token technically has repository scope; code constrains its push destination. It never executes downloaded data as code. No account-following, stars, discussions-write, issues-write, pull-requests-write or administration scopes are requested.

GitHub may deny workflow creation to the connected GitHub App. If that happens, retain the tested package and identify the exact missing workflow permission. Do not call source code deployed or schedules active until the remote ref and workflow runs have been inspected.

## State lifecycle

The collector restores `growth-data:state.sqlite3`, then commits per-response cache checkpoints. A complete collection atomically inserts the daily snapshot with its report. Failed collections cannot create follower-loss events or publish partial growth metrics. Snapshots retain 90 days. API cache entries overwrite stable endpoint keys; no follower email harvesting occurs. One credential-free public-profile HTML request observes actually displayed badges. Failure of that UI read is reported as unavailable without retrying or inferring an award.

The collector always uploads its `var/` directory when the campaign runs, including failure-state suspension markers. A separate trusted job copies only the SQLite database and named JSON/Markdown reports to the data branch. It uses a fast-forward-only push. A conflict or push denial fails instead of overwriting another checkpoint; the run artifact remains recoverable for 45 days. Scheduled runs after 21 December execute the regression gate/window check but make no API collection or state commits.

The state branch and run artifacts contain public relationship identifiers and cached public API data. On a public profile repository, the data branch is public. Do not enable private-resource or sensitive sponsorship collection in this deployment.

## Signals

Structured log events: `complete`, `unchanged`, `deferred`, `halted`, `failed`, `operator_reset`, `campaign_inactive`. API bodies, credentials and arbitrary exception text are not logged. GitHub marks a failed collector or persistence job red; use GitHub's workflow notification preferences for delivery. No email/Slack notification is configured and no continuous in-chat monitoring is claimed.

- `complete`: inspect recorded timestamp, request count, graph counts, repository evidence and queue.
- `unchanged`: same UTC day already completed; no redundant snapshot.
- `deferred` / exit 75: request budget or a primary rate window. Cache is preserved. Next scheduled run revalidates cache and retries after stored `not_before`.
- `halted` / exit 2: inspect the stored suspension reason. Permission errors, abuse/secondary-rate warnings and unexpected schemas require investigation. The engine does not evade or auto-clear restrictions.
- No new report: the previous report is historical. Its `observed_at` must not be presented as current.

## Recovery

1. Inspect the failed run and download its checkpoint artifact. Confirm the most recent complete report date.
2. For primary limits, wait until `not_before`. Do not increase request rates or rotate accounts.
3. For invalid permissions, fix the minimum required configuration or disable the optional capability. A 403 is not automatically treated as a rate limit.
4. For schema failures or abuse warnings, resolve the actual cause. Inspect the SQLite `kv` suspension marker locally without printing cached bodies.
5. Only after review, run `python3.12 -m growth.cli --state PATH --resume-after-review`. This is an explicit local operator action; there is no remotely supplied reset input.
6. If persistence failed, restore the artifact to the data branch with a normal reviewed fast-forward commit. Never delete the database to hide a suspension.

Transient network/5xx failures retry at most four times with timeouts, exponential backoff and jitter. There is no automatic source-code rollback: blindly undoing concurrent user changes would violate preservation. Invalid configuration is rejected before collection. For a source regression, stop the campaign workflow, revert the specific deployment commit normally and keep the data branch/artifacts. Tests run before the collector has an API token in its environment.

## Checks and limits

Run unit/integration fixtures, source scan, YAML parsing and `bash -n persist.sh` before publishing. The source scanner detects selected GitHub token/private-key patterns and unpinned action references; it is not a comprehensive DLP product. Python's stdlib is the only runtime dependency. Third-party Actions are pinned to inspected tag SHAs; pins require periodic security review. Runner OS and Python patch releases remain managed upstream.

ETag collection is incremental at the request level. It is not a transactionally consistent GitHub graph read: changes during pagination can still occur. Numeric-ID deduplication, count rechecks, bounded pagination and major-drop detection reject common inconsistencies. Repeatedly changing graphs may need a later retry. Very large accounts can exceed the request/page budget; increase only after measuring cost, never silently truncate.
