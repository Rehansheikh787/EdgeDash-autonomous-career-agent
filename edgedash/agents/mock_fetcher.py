from __future__ import annotations

from datetime import datetime, timezone

from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash import storage


# (title, company, url, description)
# Fixed source + url → same SHA-256 hash every run → proves dedup on re-run.
_STABLE = [
    ("Data Analyst", "Flipkart",
     "https://careers.flipkart.com/da-1024",
     "Write SQL queries and build Python ETL scripts. Create Excel "
     "dashboards for business stakeholders. A/B testing experience preferred."),
    ("Senior Data Analyst", "Razorpay",
     "https://razorpay.com/jobs/senior-da-blr",
     "Own payments analytics end-to-end. Build Power BI dashboards, write "
     "advanced SQL on large-scale data. Python (pandas, numpy) required."),
    ("Business Data Analyst", "Swiggy",
     "https://careers.swiggy.com/bda-bengaluru",
     "Analyze delivery and order patterns using Tableau and SQL. Prepare "
     "weekly Excel reports for leadership. Python scripting a plus."),
    ("Data Analyst \u2014 Growth", "PhonePe",
     "https://phonepe.com/careers/da-growth",
     "Design A/B tests, build cohort analyses in SQL, and automate reporting "
     "with Python and pandas. Data visualization skills required."),
]

# (title, company, description)
# URL includes the fetch timestamp → unique row every run.
_VOLATILE = [
    ("Junior Data Analyst", "Infosys",
     "Entry-level analytics role. Write SQL queries, maintain Excel "
     "dashboards, and assist with data cleaning using Python."),
    ("Data Analyst II", "Wipro",
     "Build data pipelines in Python, create Tableau visualizations, "
     "and own stakeholder reporting. SQL proficiency mandatory."),
    ("Associate Data Analyst", "TCS",
     "Deliver data insights for cross-functional teams. SQL, Excel, "
     "and basic statistics required. Power BI or Tableau preferred."),
    ("Data Analyst \u2014 Marketing", "Myntra",
     "Analyze campaign performance and customer segmentation using SQL "
     "and Python. Build Tableau dashboards for the marketing team."),
    ("Data Analyst", "Zerodha",
     "Analyze trading data and market trends. Strong SQL and Python "
     "required. Financial data and statistical modeling a plus."),
    ("Senior Data Analyst", "Meesho",
     "Lead seller-platform analytics. Advanced SQL, Python (pandas, "
     "scikit-learn), and data visualization. Mentor junior analysts."),
    ("Data Analytics Specialist", "CRED",
     "Deep-dive into engagement and retention. Build predictive models "
     "in Python, design Power BI dashboards for product leadership."),
    ("Data Analyst \u2014 Finance", "Accenture",
     "Support financial reporting with advanced Excel modeling, SQL "
     "queries, and Python automation. Accounting knowledge helpful."),
]


class MockFetcher:
    """Returns 12 fake job listings \u2014 4 stable (dedup-proof), 8 volatile."""

    @property
    def name(self) -> str:
        return "MockFetcher"

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        now = datetime.now(timezone.utc).isoformat()
        rows: list[storage.ListingInput] = []

        max_listings = (stop_conditions or {}).get("max_listings", 100)

        for title, company, url, desc in _STABLE:
            rows.append(_row(title, company, url, desc, config.target_city, now))

        for i, (title, company, desc) in enumerate(_VOLATILE):
            url = f"https://mock.jobs/volatile/{i}?t={now}"
            rows.append(_row(title, company, url, desc, config.target_city, now))

        inserted = storage.upsert_listings(db_path, rows)
        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=inserted,
            notes=f"{inserted} new listings",
        )


def _row(
    title: str, company: str, url: str,
    description: str, city: str, now: str,
) -> storage.ListingInput:
    return {
        "title": title,
        "company": company,
        "location": city,
        "url": url,
        "description": description,
        "source": "mock",
        "posted_at": now,
        "fetched_at": now,
    }
