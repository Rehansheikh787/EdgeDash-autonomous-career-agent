from __future__ import annotations

import unittest
from datetime import datetime, timezone

from edgedash.config import Config
from edgedash.planning import build_plan
from edgedash.state import SystemState


class TestPlanning(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            fetch_interval_hours=6.0,
            max_fetch_pages=5,
            max_fetch_listings=100,
            score_batch_size=25,
            score_max_seconds=120,
            gap_max_seconds=30,
        )

    def test_everything_stale_all_run(self) -> None:
        """1. Everything stale: Fetcher, Scorer, GapAnalyzer, and Verifier all run."""
        state = SystemState(
            last_fetch_at="2026-08-01T00:00:00+00:00",
            hours_since_fetch=12.5,
            unscored_count=35,
            gaps_computed_at=None,
            gaps_stale=True,
            last_cycle_verdict="complete",
            last_cycle_at="2026-08-01T00:00:00+00:00",
        )

        plan = build_plan(state, self.config)
        self.assertEqual(len(plan.tasks), 4)

        fetch_task, score_task, gap_task, verify_task = plan.tasks
        self.assertEqual(fetch_task.action, "run")
        self.assertIn("hours_since_fetch=12.5h >= 6.0h", fetch_task.reason)

        self.assertEqual(score_task.action, "run")
        self.assertIn("unscored_count=35", score_task.reason)

        self.assertEqual(gap_task.action, "run")
        self.assertIn("gaps_computed_at is null", gap_task.reason)

        self.assertEqual(verify_task.action, "run")

    def test_nothing_to_do_all_skipped(self) -> None:
        """2. Nothing to do: all agents are skipped."""
        state = SystemState(
            last_fetch_at="2026-08-20T12:00:00+00:00",
            hours_since_fetch=1.5,
            unscored_count=0,
            gaps_computed_at="2026-08-20T12:05:00+00:00",
            gaps_stale=False,
            last_cycle_verdict="complete",
            last_cycle_at="2026-08-20T12:06:00+00:00",
        )

        plan = build_plan(state, self.config)
        self.assertEqual(len(plan.tasks), 4)

        fetch_task, score_task, gap_task, verify_task = plan.tasks
        self.assertEqual(fetch_task.action, "skip")
        self.assertIn("skipped: hours_since_fetch=1.5h < 6.0h", fetch_task.reason)

        self.assertEqual(score_task.action, "skip")
        self.assertEqual(score_task.reason, "skipped: unscored_count=0")

        self.assertEqual(gap_task.action, "skip")
        self.assertEqual(gap_task.reason, "skipped: gaps_stale=False")

        self.assertEqual(verify_task.action, "skip")
        self.assertIn("skipped: no new cycle mutations to verify", verify_task.reason)

        # Verify rendered plan format
        rendered = plan.render()
        self.assertIn("[SKIP]", rendered)
        self.assertIn("Fetcher", rendered)
        self.assertIn("Scorer", rendered)
        self.assertIn("GapAnalyzer", rendered)
        self.assertIn("Verifier", rendered)

    def test_only_unscored_listings_scorer_runs(self) -> None:
        """3. Only unscored listings: Scorer and Verifier run, Fetcher and GapAnalyzer skipped."""
        state = SystemState(
            last_fetch_at="2026-08-20T12:00:00+00:00",
            hours_since_fetch=2.0,
            unscored_count=18,
            gaps_computed_at="2026-08-20T12:05:00+00:00",
            gaps_stale=False,
            last_cycle_verdict="complete",
            last_cycle_at="2026-08-20T12:06:00+00:00",
        )

        plan = build_plan(state, self.config)
        fetch_task, score_task, gap_task, verify_task = plan.tasks

        self.assertEqual(fetch_task.action, "skip")
        self.assertEqual(score_task.action, "run")
        self.assertIn("unscored_count=18", score_task.reason)
        self.assertEqual(gap_task.action, "skip")
        self.assertEqual(verify_task.action, "run")

    def test_gaps_stale_but_nothing_unscored_gap_runs(self) -> None:
        """4. Gaps stale but nothing unscored: GapAnalyzer and Verifier run, Fetcher and Scorer skipped."""
        state = SystemState(
            last_fetch_at="2026-08-20T12:00:00+00:00",
            hours_since_fetch=3.0,
            unscored_count=0,
            gaps_computed_at="2026-08-20T08:00:00+00:00",
            gaps_stale=True,
            last_cycle_verdict="complete",
            last_cycle_at="2026-08-20T11:00:00+00:00",
        )

        plan = build_plan(state, self.config)
        fetch_task, score_task, gap_task, verify_task = plan.tasks

        self.assertEqual(fetch_task.action, "skip")
        self.assertEqual(score_task.action, "skip")
        self.assertEqual(gap_task.action, "run")
        self.assertIn("gaps_stale=True", gap_task.reason)
        self.assertEqual(verify_task.action, "run")


if __name__ == "__main__":
    unittest.main()
