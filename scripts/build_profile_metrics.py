#!/usr/bin/env python3
"""Generate reproducible GitHub profile metrics from public repository metadata.

Only GitHub's supported REST API is accessed. No synthetic interactions, commits,
stars, pull requests, issues, or user contribution events are generated.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

USER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
API = "https://api.github.com"
MAX_PAGES = 10
PAGE_SIZE = 100


def fetch_public_repositories(username: str, token: str | None = None) -> list[dict]:
    """Read public repositories, with a bounded request count and hard timeouts."""
    if not USER_RE.fullmatch(username):
        raise ValueError("Invalid GitHub username")
    repos: list[dict] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "anistack72-profile-metrics/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for page in range(1, MAX_PAGES + 1):
        url = f"{API}/users/{username}/repos?type=owner&sort=full_name&per_page={PAGE_SIZE}&page={page}"
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20) as response:
            data = json.load(response)
        if not isinstance(data, list):
            raise ValueError("Unexpected GitHub REST response")
        repos.extend(item for item in data if isinstance(item, dict))
        if len(data) < PAGE_SIZE:
            break
    else:
        raise ValueError("Repository pagination limit exceeded; refusing incomplete metrics")
    return repos


def summarize(repos: list[dict], username: str, now: datetime | None = None) -> dict[str, int]:
    """Count only actual public, owned, non-fork repositories and their metrics."""
    now = now or datetime.now(timezone.utc)
    owned = [
        repo for repo in repos
        if repo.get("owner", {}).get("login", "").lower() == username.lower()
        and repo.get("private") is False
        and repo.get("fork") is False
        and not repo.get("archived", False)
    ]
    recent = 0
    cutoff = now - timedelta(days=90)
    for repo in owned:
        pushed_at = repo.get("pushed_at")
        if not pushed_at:
            continue
        try:
            dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
            if dt >= cutoff:
                recent += 1
        except (TypeError, ValueError):
            continue
    return {
        "repositories": len(owned),
        "stars": sum(max(0, int(repo.get("stargazers_count") or 0)) for repo in owned),
        "forks": sum(max(0, int(repo.get("forks_count") or 0)) for repo in owned),
        "active": recent,
    }


def render_svg(metrics: dict[str, int], username: str) -> str:
    """Render a compact responsive SVG without remote fonts or scripts."""
    cards = [
        ("FOLLOWERS", "followers"),
        ("PUBLIC REPOS", "repositories"),
        ("STARS RECEIVED", "stars"),
        ("FORKS", "forks"),
        ("ACTIVE / 90 DAYS", "active"),
    ]
    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="180" '
        'viewBox="0 0 900 180" role="img" aria-labelledby="title desc">',
        f'<title id="title">Public repository metrics for {escape(username)}</title>',
        '<desc id="desc">Current counts for public, non-fork, non-archived repositories. '
        'This display does not count or manufacture GitHub contributions.</desc>',
        '<style>',
        '.bg{fill:#0d1117}.panel{fill:#161b22;stroke:#30363d;stroke-width:1}',
        '.title{fill:#f0f6fc;font:600 16px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}',
        '.sub{fill:#8b949e;font:500 12px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}',
        '.num{fill:#58a6ff;font:700 32px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}',
        '@media(prefers-color-scheme:light){.bg{fill:#fff}.panel{fill:#f6f8fa;stroke:#d0d7de}',
        '.title{fill:#24292f}.sub{fill:#57606a}.num{fill:#0969da}}',
        '</style>',
        '<rect class="bg" x="0" y="0" width="900" height="180" rx="16"/>',
        '<text class="title" x="20" y="29">OPEN SOURCE / LIVE REPOSITORY METRICS</text>',
    ]
    for i, (label, key) in enumerate(cards):
        x = 19 + i * 177
        lines.append(f'<rect class="panel" x="{x}" y="49" width="164" height="109" rx="12"/>')
        lines.append(f'<text class="sub" x="{x + 15}" y="78">{escape(label)}</text>')
        lines.append(f'<text class="num" x="{x + 15}" y="127">{metrics[key]:,}</text>')
    lines.append('</svg>')
    return "\n".join(lines) + "\n"


def main() -> int:
    username = os.getenv("PROFILE_USERNAME", "anistack72")
    output = Path(os.getenv("METRICS_OUTPUT", "dist/profile-metrics.svg"))
    try:
        token = os.getenv("GITHUB_TOKEN")
        repos = fetch_public_repositories(username, token)
        metrics = summarize(repos, username)
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "anistack72-profile-metrics/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urlopen(Request(f"{API}/users/{username}", headers=headers), timeout=20) as response:
            user_data = json.load(response)
        metrics["followers"] = max(0, int(user_data["followers"]))
        svg = render_svg(metrics, username)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(svg, encoding="utf-8")
        print(f"Rendered {output} from public GitHub REST data: {metrics}")
        return 0
    except (ValueError, OSError, HTTPError, URLError) as exc:
        print(f"Metrics generation failed safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
