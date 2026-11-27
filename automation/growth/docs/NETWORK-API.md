# Hosted account-following executor

The `Account network API` workflow is installed in `.github/workflows/growth-network.yml`. It runs at 08:23 UTC during the campaign and supports a manual dispatch. It runs on GitHub-hosted Linux, independently of the Codex desktop or a signed-in browser. The former browser executor is disabled when `executor_backend` is `api`.

## Activation and credentials

This workflow is **not operational for account writes until the `FOLLOWER_TOKEN` repository secret exists and validates as `anistack72`**. A missing secret produces an explicit credential-required summary; a green validation job does not prove account execution occurred.

Use an expiring, fine-grained user token owned by `anistack72`, with **Account permissions → Followers → Read and write**. It does not need repository contents, administration, workflows, email or private repository access. Store it only as the Actions secret `FOLLOWER_TOKEN` in `anistack72/anistack72`. Do not put it in a prompt, source file, journal, command argument or log. The intended expiry is 22 December 2026, after this campaign ends.

The ordinary Actions `GITHUB_TOKEN` separately has repository contents write in the execution job so it can checkpoint the fixed `network-data:journal.json` path. That token cannot manage the user's following list. Test jobs have repository read access, and the user token is supplied only to the availability check and account-execution step. All third-party Actions are SHA pinned. The workflow never runs against a pull-request branch.

## Execution contract

1. Verify the token's account login and numeric ID, the authorized repository and tested default-branch SHA.
2. Restore the durable journal from the existing `network-data` branch. Missing or invalid state stops execution; it is never silently replaced with an empty quota.
3. Read the live following graph and discover up to 12 technical contributor candidates using the existing bounded collector. The policy still requires active public work, matching interests, approved discovery sources and a relevance score of at least 45.
4. Default to at most **5 follows and 1 explicitly excluded unfollow per UTC day**, with a following ceiling of 200. Configuration may reduce those values; the compiled maximums are 10 follows, 5 unfollows and 500 following. These values are engineering limits, not an assurance from GitHub that a rate is safe.
5. Reserve the action locally and persist its journal with an expected-blob lease **before** the account mutation. Confirm the resulting following state through a separate GET, then persist the confirmation. Mutations are serial and at least 60 seconds apart, measured from confirmation.
6. Never implicitly retry a PUT or DELETE. An uncertain result remains reserved in durable state and is reconciled on the next run through reads. A failed checkpoint prevents the corresponding account write. Existing or newly followed accounts are not churned to manufacture engagement.

The explicit exclusion list starts empty, so no unfollows are eligible by default. A nonreciprocal relationship or inactivity does not create a removal. Protected accounts cannot overlap exclusions. There is no star-mutation endpoint in this executor and no promise of inbound followers, received stars or achievement awards.

## Recovery

The workflow is serialized with cancellation disabled. Confirmed writes and uncertain reservations share one durable journal across runs, including the initial two browser actions from 24 November; moving to the hosted executor does not reset their daily quota.

Authentication/restriction failures stop the worker. A persistent `halt` marker requires review of the actual cause and the minimum credential correction before clearing it; do not rotate accounts or bypass GitHub restrictions. For a transport interruption, inspect the saved state and subsequent read-only reconciliation. State-branch lease conflicts and a moved main branch stop execution instead of overwriting concurrent work. Public checkpoint data contains only public relationship identities, timestamps, operation state and proof digests, never credentials or local screenshot paths.

## Primary references

- [GitHub followers REST API and required user permissions](https://docs.github.com/en/rest/users/followers).
- [Actions encrypted repository secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).
- [REST API best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).
- [GitHub's disruptive activity policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-disrupting-the-experience-of-other-users).
