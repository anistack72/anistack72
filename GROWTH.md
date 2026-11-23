# Evidence-led GitHub growth playbook

A practical operating system for attracting **real** followers and stars to [@anistack72](https://github.com/anistack72), not simulated engagement.

## Growth loop

1. **Discovery:** give each genuine project a specific description, a topical README, relevant GitHub topics, a license, a demonstration, and a social-preview image. Metadata and repository topics are configured in GitHub repository Settings where the API connector does not expose these changes.
2. **Activation:** document one-command installation or a hosted demo, expected output, system requirements, compatibility, security limits, and a short video/GIF where useful.
3. **Trust:** publish tests, CI badges that link to actual checks, reproducible release assets, changelog entries, and honest known limitations.
4. **Conversion:** link the tool to the profile, link related tools to each other when genuinely relevant, provide a restrained “Follow for releases” and “Star if useful” call to action. Do not use a reward, gate, trade, or misleading claim.
5. **Retention:** prioritize user feedback, real issues, useful enhancements, documentation fixes, accessible examples, and responsive review. Star/follower growth is a **result** to measure, not an activity to manufacture.

## Focus repositories

| Repository | Audience | Lead with |
| --- | --- | --- |
| [web-audit-workbench](https://github.com/anistack72/web-audit-workbench) | Web application engineers | Bounded, same-origin security diagnostics and clear reports |
| [ai-runtime-doctor](https://github.com/anistack72/ai-runtime-doctor) | Developers using Ollama or LM Studio | Non-invasive local runtime diagnosis |
| [mac-release-gate](https://github.com/anistack72/mac-release-gate) | macOS application developers | Reproducible release verification |
| [security-report-kit](https://github.com/anistack72/security-report-kit) | DevSecOps teams | Actionable redacted scanner reports |
| [asset-budget](https://github.com/anistack72/asset-budget) | Web performance teams | Build-size budgets and actionable output |
| [engineering-playbook](https://github.com/anistack72/engineering-playbook) | Software engineers | Reusable, real-world technical checklists |

## High-signal release campaign

- Choose **one** mature repo first. Validate that README features correspond to runnable code.
- Ship a real tagged release with a tested example and a concise “before / after” problem statement.
- Share a **single useful technical write-up** with the relevant community when its rules allow; disclose authorship and answer questions. Do not auto-cross-post or auto-DM.
- Seek feedback from maintainers only when the work directly relates to their issue or project; never mass-comment, auto-follow, auto-star or exchange stars.
- Record weekly public follower counts, stars, downloads when measurable, inbound issues, and actual users. Avoid hard targets detached from useful work.
- Pin the 4–6 best repositories through the native GitHub profile UI.

## Safe automation boundaries

Allowed: read-only GitHub API monitoring, scheduled SVG refresh, test/build checks, Dependabot security updates, release-note drafts, periodic issue triage summaries, and deterministic documentation generation when the **source data genuinely changed**.

Not enabled: follower bots, star bots, coordinated reciprocal engagement, automatically opening/merging meaningless PRs, fake accounts, unsolicited direct messages, commit backdating, bulk issue creation, scraping email addresses, or fictional achievements.

Every workflow must use minimal permissions, action SHA pins, bounded requests, idempotence, reasonable daily frequency, timeout and failure handling. Publishing changes to code should be reviewed; only actual generated profile assets may be updated automatically.

## Metrics definitions

- **Followers** = actual GitHub account follower count, not unique views.
- **Stars received** = sum of GitHub API stargazers_count on public non-fork non-archived owned repositories (not stars given).
- **Active / 90 days** = public qualifying repositories pushed within the past 90 days, not count of user contributions.
- **Contribution snake** = visualization of GitHub's existing contribution calendar, not a source of contributions.
- **Achievements** = actual GitHub-awarded badges; do not imply a synthetic workflow has earned them.

## Operations

The [verified profile workflow](.github/workflows/profile-visuals.yml) runs daily and on manual dispatch, tests local logic and writes changed SVG files to the dedicated `profile-assets` branch. Static public profile README sources those assets. The first execution and publishing permissions must be reviewed after this pull request is merged.

If no assets appear after first run, inspect Actions job logs, GitHub Actions repository workflow permissions, and whether the repository permits `GITHUB_TOKEN` to create/push `profile-assets`. Never add a personal access token merely to bypass a protection.

## References

- [GitHub acceptable-use policy](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies)
- [GitHub repository best practices](https://docs.github.com/en/repositories/creating-and-managing-repositories/best-practices-for-repositories)
- [Customizing and pinning items on a profile](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/pinning-items-to-your-profile)
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)
- [Platane/snk](https://github.com/Platane/snk)
