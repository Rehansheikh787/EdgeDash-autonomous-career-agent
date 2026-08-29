from __future__ import annotations

import unittest
from datetime import datetime, timezone

from edgedash.config import Config
from edgedash.verification import (
    check_extraction_sanity,
    check_freshness,
    check_gap_sample_size,
    check_score_spread,
    run_all_checks,
)


class TestVerification(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            min_score_spread=10,
            min_score_stdev=5.0,
            max_empty_extraction_pct=20.0,
            max_skills_per_listing=20,
            min_gap_sample=3,
            max_data_age_days=3.0,
        )
        self.now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)

    # ── 1. check_score_spread ─────────────────────────────────────────

    def test_score_spread_passing(self) -> None:
        """Passing: healthy spread and standard deviation."""
        scores = [25, 40, 55, 70, 85]
        res = check_score_spread(scores, self.config)
        self.assertTrue(res.passed)
        self.assertEqual(res.observed["spread"], 60)
        self.assertGreaterEqual(res.observed["stdev"], 5.0)

    def test_score_spread_failing_compressed(self) -> None:
        """Failing: scores clustered tightly (spread < 10, stdev < 5)."""
        scores = [50, 51, 52, 51, 50]
        res = check_score_spread(scores, self.config)
        self.assertFalse(res.passed)
        self.assertIn("threshold 10", res.message)

    def test_score_spread_fewer_than_five(self) -> None:
        """Fewer than 5 scores: passes trivially."""
        scores = [50, 52, 51]
        res = check_score_spread(scores, self.config)
        self.assertTrue(res.passed)
        self.assertIn("fewer than 5 scores", res.message)

    # ── 2. check_extraction_sanity ────────────────────────────────────

    def test_extraction_sanity_passing(self) -> None:
        """Passing: clean extraction with low empty rate and normal skill counts."""
        facts = [
            {"required_skills": ["python", "sql"]},
            {"required_skills": ["tableau"]},
            {"required_skills": ["python", "excel", "pandas"]},
            {"required_skills": ["statistics"]},
            {"required_skills": ["sql", "power bi"]},
        ]
        res = check_extraction_sanity(facts, self.config)
        self.assertTrue(res.passed)
        self.assertEqual(res.observed["empty_pct"], 0.0)

    def test_extraction_sanity_failing_too_many_empty(self) -> None:
        """Failing: >20% empty required_skills."""
        facts = [
            {"required_skills": []},
            {"required_skills": []},
            {"required_skills": ["python"]},
            {"required_skills": ["sql"]},
            {"required_skills": ["excel"]},
        ]  # 2/5 = 40% empty
        res = check_extraction_sanity(facts, self.config)
        self.assertFalse(res.passed)
        self.assertEqual(res.observed["empty_pct"], 40.0)
        self.assertIn("exceeds threshold 20.0%", res.message)

    def test_extraction_sanity_failing_skills_dump(self) -> None:
        """Failing: >20 skills in a single listing (possible sentence hallucination)."""
        facts = [
            {"required_skills": [f"skill_{i}" for i in range(25)]},
            {"required_skills": ["python", "sql"]},
        ]
        res = check_extraction_sanity(facts, self.config)
        self.assertFalse(res.passed)
        self.assertEqual(res.observed["max_skills_found"], 25)
        self.assertIn("exceeds threshold 20", res.message)

    # ── 3. check_gap_sample_size ──────────────────────────────────────

    def test_gap_sample_size_passing(self) -> None:
        """Passing: top gap backed by >= 3 listings."""
        gaps = [
            {"skill": "kubernetes", "listings_blocked": 5, "opportunity_cost": 3.8},
            {"skill": "docker", "listings_blocked": 4, "opportunity_cost": 2.5},
        ]
        res = check_gap_sample_size(gaps, self.config)
        self.assertTrue(res.passed)
        self.assertEqual(res.observed["top_sample"], 5)

    def test_gap_sample_size_failing_rumour(self) -> None:
        """Failing: top gap backed by only 1 listing (< 3)."""
        gaps = [
            {"skill": "obscure_lang", "listings_blocked": 1, "opportunity_cost": 0.9},
        ]
        res = check_gap_sample_size(gaps, self.config)
        self.assertFalse(res.passed)
        self.assertEqual(res.observed["top_sample"], 1)
        self.assertIn("minimum threshold 3", res.message)

    # ── 4. check_freshness ────────────────────────────────────────────

    def test_freshness_passing(self) -> None:
        """Passing: fetched 1 day ago (<= 3 days)."""
        fetch_str = "2026-08-23T12:00:00+00:00"  # 1 day ago
        res = check_freshness(fetch_str, self.config, now=self.now)
        self.assertTrue(res.passed)
        self.assertEqual(res.observed["age_days"], 1.0)

    def test_freshness_failing_stale(self) -> None:
        """Failing: fetched 5 days ago (> 3 days)."""
        fetch_str = "2026-08-19T12:00:00+00:00"  # 5 days ago
        res = check_freshness(fetch_str, self.config, now=self.now)
        self.assertFalse(res.passed)
        self.assertEqual(res.observed["age_days"], 5.0)

    def test_freshness_failing_none(self) -> None:
        """Failing: None timestamp."""
        res = check_freshness(None, self.config, now=self.now)
        self.assertFalse(res.passed)

    # ── 5. run_all_checks ─────────────────────────────────────────────

    def test_run_all_checks_all_pass(self) -> None:
        """All checks pass -> Verdict is passed."""
        scores = [30, 45, 60, 75, 90]
        facts = [{"required_skills": ["python", "sql"]}] * 5
        gaps = [{"skill": "kubernetes", "listings_blocked": 4}]
        fetch_str = "2026-08-24T06:00:00+00:00"

        verdict = run_all_checks(scores, facts, gaps, fetch_str, self.config, now=self.now)
        self.assertTrue(verdict.passed)
        self.assertEqual(len(verdict.failed_checks), 0)
        self.assertIn("All 4 verification check(s) passed", verdict.summary)

    def test_run_all_checks_with_failures(self) -> None:
        """Score spread fails -> Verdict is failed."""
        scores = [50, 50, 50, 50, 50]  # spread 0
        facts = [{"required_skills": ["python"]}] * 5
        gaps = [{"skill": "k8s", "listings_blocked": 4}]
        fetch_str = "2026-08-24T06:00:00+00:00"

        verdict = run_all_checks(scores, facts, gaps, fetch_str, self.config, now=self.now)
        self.assertFalse(verdict.passed)
        self.assertEqual(len(verdict.failed_checks), 1)
        self.assertEqual(verdict.failed_checks[0].name, "score_spread")


if __name__ == "__main__":
    unittest.main()
