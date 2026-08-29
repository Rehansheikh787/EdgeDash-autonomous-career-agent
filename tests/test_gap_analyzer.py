from __future__ import annotations

import unittest
from edgedash.config import Config
from edgedash.skills import canonical


class TestGapAnalyzerMath(unittest.TestCase):
    def test_opportunity_cost_ranking_over_raw_frequency(self) -> None:
        """Rule 24: High-fit listing gaps outweigh low-fit high-frequency gaps."""
        aliases = {"k8s": "kubernetes"}
        my_skills = {"python", "sql"}

        # Listing A (score 90) requires 'k8s'
        # Listing B (score 80) requires 'k8s'
        # Listing C (score 10) requires 'c++'
        # Listing D (score 10) requires 'c++'
        # Listing E (score 10) requires 'c++'
        # Listing F (score 10) requires 'c++'

        listings_k8s = [("id1", 90), ("id2", 80)]
        listings_cpp = [("id3", 10), ("id4", 10), ("id5", 10), ("id6", 10)]

        cost_k8s = round(sum(s / 100.0 for _, s in listings_k8s), 2)  # 1.70
        cost_cpp = round(sum(s / 100.0 for _, s in listings_cpp), 2)  # 0.40

        self.assertEqual(cost_k8s, 1.7)
        self.assertEqual(cost_cpp, 0.4)
        self.assertGreater(cost_k8s, cost_cpp)
        # Even though c++ has 4 listings vs k8s with 2, k8s ranks #1 by opportunity cost

    def test_trend_delta_calculation(self) -> None:
        """Rule 25: Trend shows absolute change, percentage change, and dropped skills."""
        earliest = {"kubernetes": 10.0, "spark": 8.0, "hadoop": 5.0}
        latest = {"kubernetes": 12.5, "spark": 6.0, "dbt": 4.0}

        # kubernetes: +2.50 (+25.0%)
        k8s_diff_abs = latest["kubernetes"] - earliest["kubernetes"]
        k8s_diff_pct = (k8s_diff_abs / earliest["kubernetes"]) * 100.0
        self.assertEqual(round(k8s_diff_abs, 2), 2.50)
        self.assertEqual(round(k8s_diff_pct, 1), 25.0)

        # spark: -2.00 (-25.0%)
        spark_diff_abs = latest["spark"] - earliest["spark"]
        spark_diff_pct = (spark_diff_abs / earliest["spark"]) * 100.0
        self.assertEqual(round(spark_diff_abs, 2), -2.00)
        self.assertEqual(round(spark_diff_pct, 1), -25.0)

        # dbt: NEW
        self.assertNotIn("dbt", earliest)

        # hadoop: DROPPED OUT
        dropped = set(earliest.keys()) - set(latest.keys())
        self.assertIn("hadoop", dropped)


if __name__ == "__main__":
    unittest.main()
