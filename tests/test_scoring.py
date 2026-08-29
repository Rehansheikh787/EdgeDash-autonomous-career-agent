from __future__ import annotations

import unittest
from datetime import datetime, timezone

from edgedash.config import Config
from edgedash.scoring import score_listing


class TestScoring(unittest.TestCase):
    def setUp(self) -> None:
        self.base_config = Config(
            target_role="Data Analyst",
            target_city="Bengaluru",
            my_skills=["sql", "python", "tableau"],
            target_seniority="mid",
            weight_skill_match=0.45,
            weight_seniority_fit=0.25,
            weight_location_fit=0.15,
            weight_recency=0.15,
        )

    def test_perfect_match(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        listing = {
            "title": "Data Analyst",
            "location": "Bengaluru",
            "posted_at": now_iso,
        }
        facts = {
            "required_skills": ["SQL", "Python"],
            "nice_to_have": ["Tableau"],
            "seniority": "mid",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["components"]["skill_match"], 1.0)
        self.assertEqual(result["components"]["seniority_fit"], 1.0)
        self.assertEqual(result["components"]["location_fit"], 1.0)
        self.assertEqual(result["components"]["recency"], 1.0)
        self.assertIn("no skill gaps", result["reason"])

    def test_zero_match(self) -> None:
        listing = {
            "title": "Chef",
            "location": "London",
            "posted_at": "2020-01-01T00:00:00+00:00",
        }
        facts = {
            "required_skills": ["baking", "pastry"],
            "nice_to_have": ["french cuisine"],
            "seniority": "lead",
            "remote_ok": False,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["components"]["skill_match"], 0.0)
        self.assertEqual(result["components"]["location_fit"], 0.1)
        self.assertEqual(result["components"]["recency"], 0.0)
        self.assertIn("gap: baking, pastry", result["reason"])

    def test_empty_required_skills(self) -> None:
        listing = {
            "title": "General Analyst",
            "location": "Bengaluru",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": [],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": False,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["components"]["skill_match"], 0.5)
        self.assertIn("no required skills listed", result["reason"])

    def test_null_posted_at(self) -> None:
        listing = {
            "title": "Data Analyst",
            "location": "Bengaluru",
            "posted_at": None,
        }
        facts = {
            "required_skills": ["sql"],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["components"]["recency"], 0.5)
        self.assertIn("post date unknown", result["reason"])

    def test_null_remote_ok(self) -> None:
        listing = {
            "title": "Data Analyst",
            "location": None,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": ["sql"],
            "nice_to_have": [],
            "seniority": "mid",
            "remote_ok": None,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["components"]["location_fit"], 0.5)
        self.assertIn("location unstated", result["reason"])

    def test_seniority_three_bands_off(self) -> None:
        self.base_config.target_seniority = "junior"
        listing = {
            "title": "Lead Architect",
            "location": "Bengaluru",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {
            "required_skills": ["sql"],
            "nice_to_have": [],
            "seniority": "lead",
            "remote_ok": True,
        }

        result = score_listing(listing, facts, self.base_config)
        self.assertEqual(result["components"]["seniority_fit"], 0.0)
        self.assertIn("seniority mismatch", result["reason"])

    def test_multi_location_country_and_remote_matching(self) -> None:
        self.base_config.target_locations = ["India", "Bengaluru", "Remote"]
        
        # Test listing in India (different city, e.g. Mumbai)
        listing_mumbai = {
            "title": "Data Analyst",
            "location": "Mumbai, India",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        facts = {"required_skills": ["sql"], "nice_to_have": [], "seniority": "mid", "remote_ok": False}
        res_mumbai = score_listing(listing_mumbai, facts, self.base_config)
        self.assertEqual(res_mumbai["components"]["location_fit"], 1.0)

        # Test worldwide remote listing
        listing_remote = {
            "title": "Data Analyst",
            "location": "Worldwide / Remote",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        res_remote = score_listing(listing_remote, facts, self.base_config)
        self.assertEqual(res_remote["components"]["location_fit"], 1.0)

        # Test unrelated location
        listing_berlin = {
            "title": "Data Analyst",
            "location": "Berlin, Germany",
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
        res_berlin = score_listing(listing_berlin, facts, self.base_config)
        self.assertEqual(res_berlin["components"]["location_fit"], 0.1)


if __name__ == "__main__":
    unittest.main()
