# Evidence-led GitHub growth engine

Read-only public GitHub intelligence for **anistack72**, with a bounded campaign from **21 November to 21 December 2026**. Python **3.12**, SQLite, no application dependencies. The implementation belongs in `automation/growth/` of the existing profile repository; its two workflow files belong in the repository root `.github/workflows/`.

The engine collects follower graphs, detects observed relationship changes, ranks repositories and contributor opportunities, drafts announcements, records public achievement evidence and prepares daily/weekly briefs. It does not manufacture adoption or certify account authenticity. Received stars and follower counts are outcomes, not tasks it can cause directly.

## Run locally

```sh
python3.12 -m unittest discover -s tests -v
python3.12 security_check.py
python3.12 -m growth.cli --no-graphql
```

For authenticated public REST and fixed GraphQL **queries**, supply `GITHUB_TOKEN` through your credential environment. Never paste it into the command line, a configuration file, an issue, or a commit. The Actions collector uses the ephemeral repository token with `contents: read`. No PAT is needed for the default public collection. Missing public GraphQL access is an explicit deployment test, not a reason to request broad account scopes.

`--dry-run` performs live read-only collection against a disposable copy of state and exports a report to the specified output directory. It does not persist the original database. Offline simulation is covered by deterministic transport fixtures in the regression suite. `--no-discovery`, `--no-graphql`, and `--budget N` let operators bound a diagnostic run. An existing complete UTC-day checkpoint is exported without another collection.

## What is implemented

- REST pagination following GitHub `Link` headers; bounded collections fail without committing partial snapshots.
- Stable numeric account IDs for rename-safe relationship differences, mutual sets and graph-source overlap.
- API cache with ETags and preserved pagination links. Cache entries are committed as recovery checkpoints during collection.
- Serial requests, bounded per-run budget, primary rate-limit deferral, jittered transient retries, persistent suspension on permission/abuse/schema failures.
- Explicit risk classification. Only reads and local drafts pass the controller. External mutation methods are absent.
- Contributor discovery from configured relevant repositories, topic/language matching, transparent activity signals and explicit bot-account exclusion. This is a small heuristic sample, not exhaustive bot detection.
- A 0–100 opportunity heuristic using the requested **30/25/20/15/10** weights, component evidence and exact-tree validation manifests.
- Daily snapshots and net deltas, weekly deltas once history exists, 90-day snapshot retention, priority-ordered engineering recommendations and deterministic draft IDs.
- A conservative achievement state representation. API observations never imply a GitHub award.
- A daily GitHub Actions schedule at **07:37 UTC / 08:37 Paris** during this campaign, on-push checks, a final-day report, serialized workflow execution, local database locks, isolated data persistence and recoverable run artifacts.

## Automation boundary

Generated analytics, evidence, ranked recommendations and release drafts execute automatically. Changes to other repositories require actual scoped engineering work and tests; this code does not let an LLM blindly change arbitrary source. The collector itself does not publish releases, social posts, discussion answers, follows or merges. Separate trusted release workflows now operate in all five existing tools: `ai-runtime-doctor`, `asset-budget`, `web-audit-workbench`, `mac-release-gate` and `security-report-kit` under `anistack72`: after the complete six-job platform/Node matrix passes, they validate the distributable, create or resume a versioned draft, verify downloaded asset bytes and publish it. Existing versions and tags are never overwritten. No npm registry or promotional posting channel is connected.

A separate daily Codex automation, **Maintenance et contributions vérifiées**, is active at 09:15 Europe/Paris through 21 December. It prioritizes useful improvements and CI/release failures across the five owned projects, then checks upstream feedback and potential reproducible contributions. Own-repository PRs may be merged automatically only after the exact source passes all six platform/Node test jobs and existing protection requirements. Each tool also runs daily read-only regression checks using ephemeral repository tokens. No routine human approval or user-supplied personal token is required for the installed workflows. It respects project admission and AI policies, publishes at most one useful verified upstream PR per execution, and skips when no suitable change exists. A daily execution does not promise a daily contribution or third-party merge. This is distinct from the analytics collector and depends on the connected tools and Codex automation environment. Existing README artwork and the separate profile PR are preserved.

The demand component is explicitly a sparse stars/forks proxy, not measured developer demand. Zero observed demand remains zero. File presence is not proof of functionality. `evidence/repository-validation.json` records locally executed checks/demonstrations or successful CI against exact Git trees; validation expires when a tree changes. CI and deployment results are reported separately.

Campaign attribution and visitor-to-star conversion remain **unknown**: public GitHub APIs do not provide causal attribution. Repository traffic requires additional administration-read permission; default collection does not request it. Badge verification reads the public profile without credentials and requires matching account links, GitHub badge attributes and official image origins. It records visible awards only; absent, hidden or unavailable badges remain unknown. This HTML adapter can require updates if GitHub changes its UI.

See [operations](docs/OPERATIONS.md), [research](docs/RESEARCH.md) and [campaign](docs/CAMPAIGN.md).

## Selective account following

The separate [network executor](docs/NETWORK.md) is now installed for authorized, relevant follows and explicit policy exclusions. It uses a persistent SQLite action journal, fresh complete discovery reports, strict daily limits, reservation before mutation, and browser screenshots after confirmation. Its `network-policy.json` starts with an empty exclusion list and protects the two existing technical follows. The daily connected Codex agent executes the browser steps; the read-only analytics collector never receives account-following credentials. All other external interaction drafts retain their existing approval boundary.

## Hosted API execution

The [hosted network executor](docs/NETWORK-API.md) replaces the browser dependency for account-following operations. Its default policy allows up to five relevant follows per UTC day, with a configurable ceiling and a separate explicit-exclusion unfollow budget. The `Account network API` workflow requires the narrowly scoped `FOLLOWER_TOKEN` Actions secret before it can perform account writes. Durable reservations are committed before mutations and verified afterward. Missing credentials mean **pending activation**, not a functioning account executor. The Codex maintenance automation monitors this workflow and does not duplicate its writes through the browser.
