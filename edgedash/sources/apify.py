from __future__ import annotations

import os
from typing import Any

from edgedash.config import Config
from edgedash.sources.base import register
from edgedash.sources.http import get_json


@register
class ApifySource:
    """Apify job scraper actor source."""

    @property
    def name(self) -> str:
        return "apify"

    def fetch(self, config: Config) -> list[dict[str, Any]]:
        token = os.environ.get("APIFY_TOKEN")
        if not token:
            print("[apify] no APIFY_TOKEN, skipping")
            return []

        url = "https://api.apify.com/v2/acts/apify~job-scrappers/run-sync-get-dataset-items"
        params = {
            "token": token,
            "query": config.target_role,
            "location": config.target_city,
            "limit": 100,
            "maxItems": 100,
        }

        data = get_json(url, params=params)
        items = data if isinstance(data, list) else (data.get("items") or data.get("data") or [])
        if not isinstance(items, list):
            items = []

        items = items[:100]
        print(f"[apify] Raw results: {len(items)}")

        return [_normalise_item(item) for item in items if isinstance(item, dict)]


def _clean_val(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    return s


def _normalise_item(item: dict[str, Any]) -> dict[str, Any]:
    ext_id = _clean_val(
        item.get("id") or item.get("jobId") or item.get("positionId") or item.get("url")
    )
    return {
        "source": "apify",
        "external_id": ext_id,
        "title": _clean_val(item.get("title") or item.get("positionName") or item.get("jobTitle")),
        "company": _clean_val(item.get("company") or item.get("companyName") or item.get("company_name")),
        "location": _clean_val(item.get("location") or item.get("jobLocation")),
        "url": _clean_val(item.get("url") or item.get("jobUrl") or item.get("link")),
        "description": _clean_val(item.get("description") or item.get("jobDescription")),
        "posted_at": _clean_val(item.get("postedAt") or item.get("postedDate") or item.get("created_at")),
        "raw": item,
    }
