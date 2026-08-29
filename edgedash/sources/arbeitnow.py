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
        kw_filtered = [j for j in raw_jobs if _matches_keywords(j, config.keywords)]
        strict_filtered = [j for j in kw_filtered if _matches_location(j, config.target_city)]

        survived_jobs = strict_filtered
        if len(strict_filtered) < 5 and config.target_city:
            print(
                f"[arbeitnow] Relaxing location filter for '{config.target_city}': "
                f"only {len(strict_filtered)} strict match(es), keeping {len(kw_filtered)} keyword match(es) across all locations."
            )
            survived_jobs = kw_filtered

        print(f"[arbeitnow] Raw results: {total_raw} | Survived filtering: {len(survived_jobs)}")

        return [_normalise_job(job) for job in survived_jobs]


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


def _matches_location(job: dict[str, Any], target_city: str) -> bool:
    if not target_city:
        return True
    loc = str(job.get("location") or "").lower()
    is_remote = bool(job.get("remote"))
    target = target_city.lower()
    return target in loc or is_remote or "remote" in loc


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
