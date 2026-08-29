import unittest

from edgedash.config import Config
from edgedash.sources.arbeitnow import _matches_location, _matches_role


class TestArbeitnowFiltering(unittest.TestCase):
    def setUp(self):
        self.config = Config(
            target_role="Data Analyst",
            target_city="Bengaluru",
            target_country="India",
            target_locations=["India", "Bengaluru", "Remote", "Worldwide"],
            keywords=["sql", "python", "power bi", "excel"],
        )

    def test_role_filtering(self):
        # Matching titles
        self.assertTrue(_matches_role({"title": "Senior Data Analyst"}, self.config.target_role, self.config.keywords))
        self.assertTrue(_matches_role({"title": "BI & Analytics Specialist"}, self.config.target_role, self.config.keywords))
        self.assertTrue(_matches_role({"title": "Business Intelligence Analyst"}, self.config.target_role, self.config.keywords))
        self.assertTrue(_matches_role({"title": "SQL Data Reporting Analyst"}, self.config.target_role, self.config.keywords))

        # Non-matching titles
        self.assertFalse(_matches_role({"title": "Managing Director, UK"}, self.config.target_role, self.config.keywords))
        self.assertFalse(_matches_role({"title": "Game Producer"}, self.config.target_role, self.config.keywords))
        self.assertFalse(_matches_role({"title": "Fullstack Softwareentwickler"}, self.config.target_role, self.config.keywords))
        self.assertFalse(_matches_role({"title": "Taxes TOM Consultant"}, self.config.target_role, self.config.keywords))

    def test_location_filtering(self):
        # Matching locations
        self.assertTrue(_matches_location({"location": "Bengaluru, India", "remote": False}, self.config))
        self.assertTrue(_matches_location({"location": "Remote - Worldwide", "remote": True}, self.config))
        self.assertTrue(_matches_location({"location": "Remote", "remote": True}, self.config))

        # Foreign restricted locations should be rejected
        self.assertFalse(_matches_location({"location": "Remote in Deutschland", "remote": True}, self.config))
        self.assertFalse(_matches_location({"location": "UK - Remote", "remote": True}, self.config))
        self.assertFalse(_matches_location({"location": "Berlin, Germany", "remote": False}, self.config))
        self.assertFalse(_matches_location({"location": "Munich", "remote": False}, self.config))


if __name__ == "__main__":
    unittest.main()
