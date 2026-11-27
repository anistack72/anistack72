# Selective following executor

**Current backend:** the hosted [REST executor](NETWORK-API.md) is selected by policy. The browser procedure below is retained as a historical fallback and is disabled in the CLI while the API backend is selected. Its initial two actions remain in the migrated journal; there is no quota reset. The hosted workflow still needs its account credential before activation.

This executor manages the account's following list. It does not acquire followers or stars on command. It uses the existing signed-in GitHub browser through the daily Codex automation. The analytics collector and its read-only repository token remain separate.

## Policy and execution

`network-policy.json` authorizes active contributors discovered in configured technical communities with matching interests and a relevance score of at least 45. A complete report no older than 36 hours is required. Public identities, graph completeness, account ownership, the campaign deadline and following capacity are checked before an action is reserved.

The compiled ceilings are two follows and one unfollow per UTC day. The configured following ceiling is 30; mutations are at least 60 seconds apart, measured conservatively from the previous confirmation. An unresolved action blocks all new mutations. These are conservative engineering limits, not a GitHub-approved safe rate. Uncertain attempts consume the quota and reserve following capacity. Never retry a click after an uncertain result: inspect the resulting state and reconcile it first.

Unfollows require exact usernames in the explicit `exclude` list. That list starts empty. Accounts in `protected` are retained; an overlap stops execution. Follower reciprocity and inactivity do not generate removals. Previously removed accounts are not automatically followed again. Update exclusions only when the user explicitly identifies accounts to remove; do not invent exclusions to manufacture churn.

## Daily browser procedure

Use the local deployed package under `outputs/github-growth` in this chat's workspace. Preserve its `var/network.sqlite3` journal across executions. Obtain the current report from the existing growth-data branch when the local checkpoint is stale; do not fabricate or backdate a report. A stale or incomplete report blocks mutations.

```sh
python3.12 -m growth.network --state var/network.sqlite3 plan
```

The command returns `actions` and `in_flight`. First inspect any in-flight account in the existing browser and reconcile the actual state without repeating its mutation. For a new action, open the exact returned GitHub URL, verify the intended signed-in account and target login, inspect the current Follow/Unfollow button and current following count, then reserve the action using its returned ID:

```sh
python3.12 -m growth.network --state var/network.sqlite3 claim ACTION_ID
```

Only after a successful claim may the browser perform the one intended mutation. If the current state already matches the goal, record `unchanged` without clicking. Save a genuine JPEG screenshot showing the resulting button or the account following list. Confirm the observed state:

```sh
python3.12 -m growth.network --state var/network.sqlite3 finish ACTION_ID --observed following --result changed --proof /absolute/path/proof.jpg --source https://github.com/TARGET
```

For an unfollow, use `--observed not_following`. For an indeterminate result, use `--observed unknown --result uncertain` with the screenshot. Then stop further mutations until the UI is understood. Do not generate a screenshot or a confirmation merely to satisfy the CLI. The evidence file is hashed and its path retained; the operator must verify its visual content.

On login failures, restrictions, CAPTCHA, API abuse messages or permission errors, stop and suspend:

```sh
python3.12 -m growth.network --state var/network.sqlite3 halt
```

The suspension persists across restarts. Review and resolve the actual cause before an operator removes the suspension marker; automatic clearing is not implemented. Keep the local journal and authenticated screenshots out of public Git commits. The daily schedule is subject to the connected session and Codex execution environment remaining available.

## Permissions and research

GitHub's [followers API](https://docs.github.com/en/rest/users/followers) requires an authenticated user token with Followers write permission, or `user:follow` for classic tokens. A repository-scoped Actions token does not provide that user permission. This deployment does not request, create, print or store a PAT; it uses the already connected browser instead. The GitHub connector currently exposes no follow/unfollow mutation tool.

The inspected [GitHub Friends Tracker](https://github.com/GoXLd/github-friends) demonstrates persistent snapshots and relationship events. This implementation adopts journaled state and deduplication, and uses relevance rather than reciprocal-follow incentives. GitHub's [disruptive activity policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-disrupting-the-experience-of-other-users) identifies high-volume following/starring as disruptive, and its [acceptable-use policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies) prohibits excessive automated bulk activity. No numeric throttle guarantees account safety.
