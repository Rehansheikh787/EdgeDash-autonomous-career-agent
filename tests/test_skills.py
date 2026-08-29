from __future__ import annotations

import unittest

from edgedash.skills import canonical


class TestCanonical(unittest.TestCase):
    def setUp(self) -> None:
        self.aliases = {
            "k8s": "kubernetes",
            "nodejs": "node",
            "node.js": "node",
            "js": "javascript",
            "postgresql": "postgres",
            "psql": "postgres",
            "gcp": "gcp",
            "google cloud": "gcp",
            "ml": "machine learning",
            "ci/cd": "ci/cd",
            "ci cd": "ci/cd",
            "cicd": "ci/cd",
        }

    def test_case_normalization(self) -> None:
        self.assertEqual(canonical("PYTHON"), "python")
        self.assertEqual(canonical("PostgreSql", self.aliases), "postgres")
        self.assertEqual(canonical("TypeSCRIPT"), "typescript")

    def test_whitespace_normalization(self) -> None:
        self.assertEqual(canonical("   data    engineering   "), "data engineering")
        self.assertEqual(canonical("\t\n machine   learning \n\t", self.aliases), "machine learning")

    def test_parenthetical_qualifiers(self) -> None:
        self.assertEqual(canonical("kubernetes (eks)", self.aliases), "kubernetes")
        self.assertEqual(canonical("python (pandas/numpy)"), "python")
        self.assertEqual(canonical("react [v18]"), "react")
        self.assertEqual(canonical("AWS {Core}"), "aws")

    def test_aliased_term(self) -> None:
        self.assertEqual(canonical("k8s", self.aliases), "kubernetes")
        self.assertEqual(canonical("nodejs", self.aliases), "node")
        self.assertEqual(canonical("node.js", self.aliases), "node")
        self.assertEqual(canonical("js", self.aliases), "javascript")
        self.assertEqual(canonical("google cloud", self.aliases), "gcp")
        self.assertEqual(canonical("cicd", self.aliases), "ci/cd")

    def test_term_with_no_alias(self) -> None:
        self.assertEqual(canonical("docker", self.aliases), "docker")
        self.assertEqual(canonical("snowflake", self.aliases), "snowflake")
        self.assertEqual(canonical("dbt", self.aliases), "dbt")

    def test_empty_string(self) -> None:
        self.assertEqual(canonical(""), "")
        self.assertEqual(canonical("   "), "")
        self.assertEqual(canonical(None), "")
        self.assertEqual(canonical("()"), "")
        self.assertEqual(canonical("---"), "")


if __name__ == "__main__":
    unittest.main()
