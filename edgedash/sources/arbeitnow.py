from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgedash.config import Config
from edgedash.sources.base import register
from edgedash.sources.http import get_json


@register
class ArbeitnowSource:
    """Free public Arbeitnow job board API source."""

    @property
    def name(self) -> str:
        return "arbeitnow"

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        raw_jobs: list[dict[str, Any]] = []
        page = 1
        max_pages = 5
        url: str | None = "https://www.arbeitnow.com/api/job-board-api"

        while url and page <= max_pages:
            data = get_json(url)
            if not isinstance(data, dict):
                break
            page_jobs = data.get("data") or []
            if not page_jobs:
                break
            raw_jobs.extend(page_jobs)

            kw_matches_on_page = [j for j in page_jobs if _matches_keywords(j, config.keywords)]
            if config.keywords and not kw_matches_on_page:
                break

            links = data.get("links") or {}
            url = links.get("next")
            page += 1

        total_raw = len(raw_jobs)
        role_filtered = [j for j in raw_jobs if _matches_role(j, config.target_role, config.keywords)]
        loc_filtered = [j for j in role_filtered if _matches_location(j, config)]

        print(f"[arbeitnow] Raw results: {total_raw} | Role matches: {len(role_filtered)} | Survived filtering: {len(loc_filtered)}")

        return [_normalise_job(job) for job in loc_filtered]


def _matches_role(job: dict[str, Any], target_role: str, keywords: list[str]) -> bool:
    """Check if the job title aligns with the target career role (e.g. Data Analyst)."""
    title = str(job.get("title") or "").lower()
    if not target_role and not keywords:
        return True

    # Direct target role match in title
    if target_role and target_role.lower() in title:
        return True

    # Role-specific keywords in title
    role_tokens = [t.lower() for t in target_role.split() if len(t) > 2]
    if role_tokens and all(token in title for token in role_tokens):
        return True

    # Common domain synonyms for analytics / data
    if "analyst" in target_role.lower() or "data" in target_role.lower():
        data_title_indicators = [
            "data analyst",
            "business analyst",
            "bi analyst",
            "analytics",
            "business intelligence",
            "data specialist",
            "reporting analyst",
            "data visualization",
            "sql analyst",
            "insights analyst",
            "decision analyst",
        ]
        if any(ind in title for ind in data_title_indicators):
            return True

    # If title explicitly mentions primary keywords
    top_keywords = [kw.lower() for kw in keywords if len(kw) > 3][:4]
    return any(kw in title for kw in top_keywords)


def _matches_keywords(job: dict[str, Any], keywords: list[str]) -> bool:
    if not keywords:
        return True
    tags = job.get("tags")
    tags_str = " ".join(tags) if isinstance(tags, list) else str(tags or "")
    text = " ".join([
        str(job.get("title") or ""),
        str(job.get("description") or ""),
        tags_str,
    ]).lower()
    return any(kw.lower() in text for kw in keywords)


def _matches_location(job: dict[str, Any], config: Config) -> bool:
    """Match job location against target city, country, and target locations (Rule 50)."""
    loc = str(job.get("location") or "").lower()
    is_remote = bool(job.get("remote"))

    target_city = (config.target_city or "").lower().strip()
    target_country = (getattr(config, "target_country", "") or "").lower().strip()
    target_locs = [str(l).lower().strip() for l in getattr(config, "target_locations", []) if l]

    if target_city and target_city not in target_locs:
        target_locs.append(target_city)
    if target_country and target_country not in target_locs:
        target_locs.append(target_country)
    if "bengaluru" in target_locs or target_city == "bengaluru":
        if "bangalore" not in target_locs:
            target_locs.append("bangalore")

    # 1. Direct location match (e.g. Bengaluru, Bangalore, India)
    if any(tl in loc for tl in target_locs if tl and tl not in {"remote", "worldwide"}):
        return True

    # 2. Check for country-restricted remotes (e.g. "Remote in Deutschland", "UK - Remote")
    foreign_restrictions = [
        "deutschland", "germany", "uk", "united kingdom", "us only", "usa only",
        "austria", "switzerland", "france", "spain", "netherlands", "berlin", "munich",
        "london", "emea", "latam"
    ]
    # Filter out restrictions that match user preferences
    active_restrictions = [r for r in foreign_restrictions if not any(r in tl for tl in target_locs)]
    is_country_restricted = any(r in loc for r in active_restrictions)

    if is_country_restricted:
        return False

    # 3. Global / Worldwide remote
    if is_remote or "worldwide" in loc or "anywhere" in loc or loc == "remote" or "remote" in target_locs:
        return True

    return False


def _clean_val(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    return s


def _format_posted_at(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
        except Exception:
            return None
    return _clean_val(val)


def _normalise_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": "arbeitnow",
        "external_id": _clean_val(job.get("slug")),
        "title": _clean_val(job.get("title")),
        "company": _clean_val(job.get("company_name")),
        "location": _clean_val(job.get("location")),
        "url": _clean_val(job.get("url")),
        "description": _clean_val(job.get("description")),
        "posted_at": _format_posted_at(job.get("created_at")),
        "raw": job,
    }
