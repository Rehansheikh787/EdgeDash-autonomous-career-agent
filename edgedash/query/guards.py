from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.config import Config

# Session rate limit: 10 queries per 10 minutes (600s)
_SESSION_WINDOW_SEC = 600.0
_SESSION_MAX_QUERIES = 10
_SESSION_HISTORIES: dict[str, deque[float]] = defaultdict(
    lambda: deque(maxlen=_SESSION_MAX_QUERIES)
)

_INJECTION_PATTERNS = [
    r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\b",
    r"\bsystem\s+prompt\b",
    r"\bsystem\s+instruction[s]?\b",
    r"\byou\s+are\s+now\b",
    r"\bdisregard\s+(?:all\s+)?(?:previous|prior)\b",
    r"\bforget\s+(?:all\s+)?(?:previous|prior)\b",
    r"\bact\s+as\s+(?:a|an)\b",
    r"\bpretend\s+you\s+are\b",
    r"\bjailbreak\b",
]


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    sanitized_text: str
    rejection_reason: str | None = None
    user_message: str | None = None


def check_guards(
    raw_question: str,
    session_id: str,
    db_path: str,
    config: Config,
    now_ts: float | None = None,
) -> GuardResult:
    """Validate query against input guards, session rate limits, and daily caps."""
    now = now_ts or time.time()

    # 1. Global Daily Cap Check (Pre-check against DB to save API quota)
    daily_count = storage.get_daily_query_count(db_path)
    if daily_count >= config.max_daily_queries:
        return GuardResult(
            allowed=False,
            sanitized_text=raw_question,
            rejection_reason="rejected: daily cap reached",
            user_message=(
                "Daily query limit reached (200/day). "
                "The ask box is temporarily paused to preserve free-tier quotas. "
                "All dashboard data panels remain fully operational."
            ),
        )

    # 2. Per-Session Rate Limiting (10 questions per 10 minutes)
    history = _SESSION_HISTORIES[session_id]
    # Prune old timestamps
    while history and (now - history[0] > _SESSION_WINDOW_SEC):
        history.popleft()

    if len(history) >= _SESSION_MAX_QUERIES:
        oldest = history[0]
        wait_seconds = int(max(1.0, _SESSION_WINDOW_SEC - (now - oldest)))
        mins, secs = divmod(wait_seconds, 60)
        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        return GuardResult(
            allowed=False,
            sanitized_text=raw_question,
            rejection_reason="rejected: session rate limit",
            user_message=(
                f"Rate limit reached (max 10 queries per 10 minutes). "
                f"Please wait {time_str} before asking another question."
            ),
        )

    # 3. Input Guards: Empty / Whitespace
    if not raw_question or not raw_question.strip():
        return GuardResult(
            allowed=False,
            sanitized_text="",
            rejection_reason="rejected: empty input",
            user_message="Please enter a non-empty question.",
        )

    # Strip control characters (keep printable & standard whitespace)
    cleaned = "".join(c for c in raw_question if ord(c) >= 32 or c in "\t\n")
    cleaned = cleaned.strip()

    # Length guard: max 300 chars
    if len(cleaned) > 300:
        return GuardResult(
            allowed=False,
            sanitized_text=cleaned[:300],
            rejection_reason="rejected: length > 300",
            user_message="Questions must be under 300 characters. Please shorten your question.",
        )

    # Instruction injection guard: heuristic pattern matching
    lower_cleaned = cleaned.lower()
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, lower_cleaned):
            return GuardResult(
                allowed=False,
                sanitized_text=cleaned,
                rejection_reason="rejected: suspicious input",
                user_message=None,  # Standard unanswerable message used, no explanation given
            )

    # Record timestamp on passed validation
    history.append(now)
    return GuardResult(allowed=True, sanitized_text=cleaned)
