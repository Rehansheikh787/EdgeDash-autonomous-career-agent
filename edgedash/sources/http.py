from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any


class SourceError(Exception):
    """Raised when an HTTP request or source fetch fails."""


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 EdgeDash/1.0"
)


def get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10.0,
    max_retries: int = 2,
) -> dict[str, Any] | list[Any]:
    """Fetch JSON from a URL with timeout, retries, and custom headers."""
    if params:
        query_string = urllib.parse.urlencode(params)
        url = f"{url}?{query_string}" if "?" not in url else f"{url}&{query_string}"

    req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(2**attempt)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                if response.status != 200:
                    raise SourceError(f"HTTP {response.status} fetching {url}")
                body = response.read().decode("utf-8")
                return json.loads(body)
        except Exception as exc:
            last_exc = exc
            if isinstance(exc, SourceError):
                continue

    raise SourceError(f"Failed to fetch {url} after {max_retries + 1} attempts: {last_exc}") from last_exc
