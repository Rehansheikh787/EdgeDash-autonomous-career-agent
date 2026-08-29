from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from edgedash.agents.verifier import Verifier
from edgedash.config import Config
from edgedash import storage


class TestVerifierAgent(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(
            min_score_spread=10,
            min_score_stdev=5.0,
            max_empty_extraction_pct=20.0,
            max_skills_per_listing=20,
            min_gap_sample=3,
            max_data_age_days=3.0,
        )
        self.verifier = Verifier()

    @patch("edgedash.storage.get_scored_listings")
    @patch("edgedash.storage.get_all_extractions")
    @patch("edgedash.storage.get_latest_gap_snapshot")
    @patch("edgedash.storage.last_fetch_time")
    def test_verifier_passing_cycle(
        self, mock_fetch, mock_gaps, mock_facts, mock_scored
    ) -> None:
        mock_scored.return_value = [{"fit_score": s} for s in [25, 45, 65, 80, 90]]
        mock_facts.return_value = [{"required_skills": ["python", "sql"]}] * 5
        mock_gaps.return_value = {"gaps": [{"skill": "k8s", "listings_blocked": 5}]}
        now_str = datetime.now(timezone.utc).isoformat()
        mock_fetch.return_value = now_str

        res = self.verifier.run(self.config, ":memory:")
        self.assertEqual(res.status, "ok")
        self.assertIn("VERDICT: pass", res.notes)

    @patch("edgedash.storage.get_scored_listings")
    @patch("edgedash.storage.get_all_extractions")
    @patch("edgedash.storage.get_latest_gap_snapshot")
    @patch("edgedash.storage.last_fetch_time")
    def test_verifier_failing_cycle(
        self, mock_fetch, mock_gaps, mock_facts, mock_scored
    ) -> None:
        # Clustered scores that fail spread check
        mock_scored.return_value = [{"fit_score": 50}] * 5
        mock_facts.return_value = [{"required_skills": ["python"]}] * 5
        mock_gaps.return_value = {"gaps": [{"skill": "k8s", "listings_blocked": 5}]}
        mock_fetch.return_value = datetime.now(timezone.utc).isoformat()

        res = self.verifier.run(self.config, ":memory:")
        self.assertEqual(res.status, "failed")
        self.assertIn("VERDICT: fail", res.notes)
        self.assertIn("score_spread", res.notes)


if __name__ == "__main__":
    unittest.main()
