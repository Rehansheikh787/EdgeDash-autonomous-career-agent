import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from edgedash import health, storage
from edgedash.config import Config


class TestHealthReporting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()
        storage.init_db(self.db_path)
        self.config = Config(db_path=self.db_path)

    def test_database_connectivity_pass(self):
        status = health.check_health(self.db_path, self.config)
        db_check = next(c for c in status.checks if c.name == "Database Connectivity")
        self.assertEqual(db_check.status, "PASS")

    def test_listing_freshness_pass_and_fail(self):
        now = datetime.now(timezone.utc)
        # Empty DB gives WARN
        status_empty = health.check_health(self.db_path, self.config, now=now)
        freshness_empty = next(c for c in status_empty.checks if c.name == "Listing Freshness")
        self.assertEqual(freshness_empty.status, "WARN")

        # Insert fresh listing (1 hour ago)
        fresh_time = (now - timedelta(hours=1)).isoformat()
        storage.upsert_listings(
            self.db_path,
            [
                {
                    "id": "fresh-1",
                    "source": "arbeitnow",
                    "title": "Data Analyst",
                    "company": "Tech Corp",
                    "location": "Bengaluru",
                    "description": "SQL Python",
                    "url": "https://example.com/fresh",
                    "raw_text": "SQL Python",
                    "posted_at": fresh_time,
                    "fetched_at": fresh_time,
                }
            ],
        )

        status_fresh = health.check_health(self.db_path, self.config, now=now)
        freshness_check = next(c for c in status_fresh.checks if c.name == "Listing Freshness")
        self.assertEqual(freshness_check.status, "PASS")

        # Stale check with future now (5 days later)
        future_now = now + timedelta(days=5)
        status_stale = health.check_health(self.db_path, self.config, now=future_now)
        freshness_stale = next(c for c in status_stale.checks if c.name == "Listing Freshness")
        self.assertEqual(freshness_stale.status, "FAIL")
        self.assertFalse(status_stale.is_healthy)

    def test_three_consecutive_cycle_failures_triggers_alert(self):
        now = datetime.now(timezone.utc)
        # Log 3 failed cycles
        for i in range(3):
            t = (now - timedelta(hours=3 - i)).isoformat()
            storage.log_cycle(
                self.db_path,
                agent="Verifier",
                started_at=t,
                finished_at=t,
                records_touched=10,
                status="failed",
                notes=f"Test failure {i}",
            )

        status = health.check_health(self.db_path, self.config, now=now)
        failure_check = next(c for c in status.checks if c.name == "Cycle Failure Sequence")
        self.assertEqual(failure_check.status, "FAIL")
        self.assertEqual(status.overall_status, "degraded")
        self.assertFalse(status.is_healthy)


if __name__ == "__main__":
    unittest.main()
