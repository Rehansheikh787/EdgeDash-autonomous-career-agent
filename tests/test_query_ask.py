from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from edgedash import storage
from edgedash.config import Config
from edgedash.query.ask import ask


class TestQueryAsk(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.tmp.name
        self.tmp.close()
        storage.init_db(self.db_path)
        self.config = Config(db_path=self.db_path)

        storage.upsert_listings(
            self.db_path,
            [
                {
                    "source": "arbeitnow",
                    "title": "Senior Python Engineer",
                    "company": "FastTech",
                    "location": "Berlin",
                    "url": "https://example.com/fasttech",
                    "description": "Python, Docker, Kubernetes",
                    "posted_at": "2026-08-25T10:00:00+00:00",
                    "fetched_at": "2026-08-25T12:00:00+00:00",
                }
            ],
        )
        listings = storage.get_listings(self.db_path, limit=5)
        storage.update_listing_score(self.db_path, listings[0]["id"], 92, "Top seniority and skill match")

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    @patch("edgedash.llm.complete_json")
    def test_ask_successful_two_call_pipeline(self, mock_llm) -> None:
        # Call 1: Route -> best_matches with n=5
        # Call 2: Phrase -> 2-3 sentences
        mock_llm.side_effect = [
            {"tool": "best_matches", "params": {"n": 5}, "confidence": "high"},
            {"answer": "Your top match is Senior Python Engineer at FastTech with a 92/100 score."},
        ]

        ans = ask("What are my best matching jobs?", session_id="test_user", config=self.config, db_path=self.db_path)
        self.assertTrue(ans.answerable)
        self.assertEqual(ans.tool_used, "best_matches")
        self.assertEqual(len(ans.rows), 1)
        self.assertIn("FastTech", ans.text)

        # Check DB log
        self.assertEqual(storage.get_daily_query_count(self.db_path), 1)

    @patch("edgedash.llm.complete_json")
    def test_ask_unanswerable_null_tool(self, mock_llm) -> None:
        # Router returns tool: null per Rule 45
        mock_llm.return_value = {"tool": None, "params": {}, "confidence": "low"}

        ans = ask("What is the weather in Berlin?", session_id="test_user_2", config=self.config, db_path=self.db_path)
        self.assertFalse(ans.answerable)
        self.assertIsNone(ans.tool_used)
        self.assertIn("Here is what you can ask", ans.text)
        self.assertEqual(len(ans.rows), 0)

    def test_ask_guard_rejection_empty(self) -> None:
        ans = ask("   ", session_id="test_user_3", config=self.config, db_path=self.db_path)
        self.assertFalse(ans.answerable)
        self.assertIn("non-empty", ans.text)


if __name__ == "__main__":
    unittest.main()
