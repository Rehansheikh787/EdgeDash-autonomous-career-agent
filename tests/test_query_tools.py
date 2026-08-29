from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from edgedash import storage
from edgedash.config import Config
from edgedash.query.tools import (
    TOOLS,
    best_matches,
    companies_hiring,
    gap_detail,
    listing_count,
    skill_demand,
    top_gaps,
    trend,
)


class TestQueryTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.tmp.name
        self.tmp.close()
        storage.init_db(self.db_path)
        self.config = Config(db_path=self.db_path)

        # Seed sample listings
        storage.upsert_listings(
            self.db_path,
            [
                {
                    "source": "arbeitnow",
                    "title": "Backend Python Engineer",
                    "company": "Tech Corp",
                    "location": "Berlin",
                    "url": "https://example.com/job1",
                    "description": "Python, Docker, AWS",
                    "posted_at": "2026-08-25T10:00:00+00:00",
                    "fetched_at": "2026-08-25T12:00:00+00:00",
                },
                {
                    "source": "arbeitnow",
                    "title": "Frontend React Dev",
                    "company": "Design Studio",
                    "location": "Remote",
                    "url": "https://example.com/job2",
                    "description": "React, TypeScript",
                    "posted_at": "2026-08-24T10:00:00+00:00",
                    "fetched_at": "2026-08-24T12:00:00+00:00",
                },
            ],
        )
        listings = storage.get_listings(self.db_path, limit=10)
        storage.update_listing_score(self.db_path, listings[0]["id"], 85, "High Python match")
        storage.update_listing_score(self.db_path, listings[1]["id"], 40, "Missing React")

        # Seed extractions
        storage.set_extraction(
            self.db_path,
            "desc_hash_1",
            {"required_skills": ["python", "docker"], "nice_to_have": ["aws"]},
        )
        storage.set_extraction(
            self.db_path,
            "desc_hash_2",
            {"required_skills": ["react", "typescript"], "nice_to_have": []},
        )

        # Seed gap snapshot
        storage.save_gap_snapshot(
            self.db_path,
            run_id="run_1",
            computed_at="2026-08-25T12:00:00+00:00",
            sample_size=2,
            gaps=[
                {
                    "skill": "docker",
                    "listings_blocked": 1,
                    "opportunity_cost": 0.85,
                    "mean_score": 85.0,
                    "top_score": 85,
                    "example_ids": [listings[0]["id"]],
                    "also_nice_to_have": 0,
                    "confidence": "low",
                }
            ],
        )

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_tools_registered(self) -> None:
        self.assertIn("companies_hiring", TOOLS)
        self.assertIn("best_matches", TOOLS)
        self.assertIn("top_gaps", TOOLS)
        self.assertIn("gap_detail", TOOLS)
        self.assertIn("trend", TOOLS)
        self.assertIn("listing_count", TOOLS)
        self.assertIn("skill_demand", TOOLS)
        self.assertEqual(len(TOOLS), 7)

    def test_companies_hiring_clamping(self) -> None:
        now = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
        # Test negative clamping -> clamps to 1
        res = companies_hiring(self.db_path, days=-5, now=now)
        self.assertIn("rows", res)
        self.assertIn("summary", res)

        # Test extreme upper bound clamping -> clamps to 90
        res_upper = companies_hiring(self.db_path, days=500, now=now)
        self.assertEqual(len(res_upper["rows"]), 2)

    def test_best_matches(self) -> None:
        res = best_matches(self.db_path, n=1)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["fit_score"], 85)

        # Clamping
        res_clamped = best_matches(self.db_path, n=100)
        self.assertEqual(len(res_clamped["rows"]), 2)

    def test_top_gaps(self) -> None:
        res = top_gaps(self.db_path, n=5)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["skill"], "docker")

    def test_gap_detail_known_and_unknown(self) -> None:
        # Known skill
        res = gap_detail(self.db_path, skill="docker", config=self.config)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0]["company"], "Tech Corp")

        # Unknown skill -> returns empty list gracefully, never raises
        res_unknown = gap_detail(self.db_path, skill="fortran", config=self.config)
        self.assertEqual(len(res_unknown["rows"]), 0)

    def test_trend(self) -> None:
        res = trend(self.db_path, weeks=3)
        self.assertIn("summary", res)
        # Only 1 snapshot exists -> returns empty rows cleanly
        self.assertEqual(len(res["rows"]), 0)

    def test_listing_count(self) -> None:
        res = listing_count(self.db_path)
        stats = res["rows"][0]
        self.assertEqual(stats["total_listings"], 2)
        self.assertEqual(stats["scored_count"], 2)
        self.assertEqual(stats["unscored_count"], 0)

    def test_skill_demand(self) -> None:
        res = skill_demand(self.db_path, skill="python", config=self.config)
        stats = res["rows"][0]
        self.assertEqual(stats["skill"], "python")
        self.assertEqual(stats["required_count"], 1)

        # Unknown skill demand
        res_unknown = skill_demand(self.db_path, skill="rust", config=self.config)
        self.assertEqual(res_unknown["rows"][0]["required_count"], 0)


if __name__ == "__main__":
    unittest.main()
