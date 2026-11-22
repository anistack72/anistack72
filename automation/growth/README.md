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

Generated analytics, evidence, ranked recommendations and release drafts execute automatically. Changes to other repositories require actual scoped engineering work and tests; this code does not let an LLM blindly change arbitrary source. Publishing a release, social post, discussion answer, follow or merge is not implemented. No publishing channel has been connected. Existing README artwork and the separate profile PR are preserved.

The demand component is explicitly a sparse stars/forks proxy, not measured developer demand. Zero observed demand remains zero. File presence is not proof of functionality. `evidence/repository-validation.json` records locally executed checks and demonstrations against exact Git trees; validation expires when a tree changes. CI and deployment results must be reported separately.

Campaign attribution and visitor-to-star conversion remain **unknown**: public GitHub APIs do not provide causal attribution. Repository traffic requires additional administration-read permission; default collection does not request it. A missing badge may be private, hidden, delayed or unavailable. The achievement UI request returned 404 during inspection, so no award is claimed.

See [operations](docs/OPERATIONS.md), [research](docs/RESEARCH.md) and [campaign](docs/CAMPAIGN.md).
