"""Offline tests for the factual profile-metrics renderer."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "build_profile_metrics.py"
spec = importlib.util.spec_from_file_location("profile_metrics", MODULE)
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


def repo(name, stars=0, forks=0, **overrides):
    record = {
        "name": name,
        "owner": {"login": "anistack72"},
        "private": False,
        "fork": False,
        "archived": False,
        "stargazers_count": stars,
        "forks_count": forks,
        "pushed_at": "2026-11-20T12:00:00Z",
    }
    record.update(overrides)
    return record


class MetricsTests(unittest.TestCase):
    def test_excludes_forks_private_archived_and_foreign_repositories(self):
        repos = [
            repo("one", stars=3, forks=2),
            repo("forked", stars=500, fork=True),
            repo("private", stars=500, private=True),
            repo("archived", stars=500, archived=True),
            repo("foreign", stars=500, owner={"login": "elsewhere"}),
        ]
        result = profile.summarize(
            repos, "anistack72", datetime(2026, 11, 21, tzinfo=timezone.utc)
        )
        self.assertEqual(result, {
            "repositories": 1, "stars": 3, "forks": 2, "active": 1
        })

    def test_exact_ninety_day_boundary_and_missing_date(self):
        repos = [
            repo("recent", pushed_at="2026-11-20T12:00:00Z"),
            repo("old", pushed_at="2025-01-01T00:00:00Z"),
            repo("unknown", pushed_at=None),
            repo("broken", pushed_at="not-a-date"),
        ]
        result = profile.summarize(
            repos, "anistack72", datetime(2026, 11, 21, tzinfo=timezone.utc)
        )
        self.assertEqual(result["repositories"], 4)
        self.assertEqual(result["active"], 1)

    def test_svg_is_well_formed_and_deterministic(self):
        values = {"repositories": 4, "stars": 12, "forks": 2, "active": 3}
        rendered = profile.render_svg(values, "anistack72")
        self.assertEqual(rendered, profile.render_svg(values, "anistack72"))
        ET.fromstring(rendered)
        self.assertIn("STARS RECEIVED", rendered)
        self.assertNotIn("<script", rendered)


if __name__ == "__main__":
    unittest.main()
