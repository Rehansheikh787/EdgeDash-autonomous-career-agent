from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.config import Config


@dataclass(frozen=True)
class SystemState:
    """State inspection snapshot of the EdgeDash database (Rule 28)."""
    last_fetch_at: str | None
    hours_since_fetch: float | None
    unscored_count: int
    gaps_computed_at: str | None
    gaps_stale: bool
    last_cycle_verdict: str | None
    last_cycle_at: str | None


def read_state(config: Config, now: datetime) -> SystemState:
    """Read cheap system state metrics via storage module (Rule 2, 28)."""
    metrics = storage.read_system_state_metrics(config.db_path)

    last_fetch_at = metrics.get("last_fetch_at")
    hours_since_fetch: float | None = None
    if last_fetch_at:
        try:
            fetch_str = str(last_fetch_at).replace("Z", "+00:00")
            fetch_dt = datetime.fromisoformat(fetch_str)
            if fetch_dt.tzinfo is None:
                fetch_dt = fetch_dt.replace(tzinfo=timezone.utc)
            now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
            diff_seconds = (now_utc - fetch_dt).total_seconds()
            hours_since_fetch = max(0.0, diff_seconds / 3600.0)
        except Exception:
            hours_since_fetch = None

    unscored_count = int(metrics.get("unscored_count", 0))
    scored_count = int(metrics.get("scored_count", 0))
    latest_scored_at = metrics.get("latest_scored_at")
    gaps_computed_at = metrics.get("gaps_computed_at")

    # Gaps are stale if:
    # 1. No gaps have been computed yet but scored listings exist
    # 2. Latest scored listing is newer than the last gaps computation
    if gaps_computed_at is None:
        gaps_stale = (scored_count > 0)
    else:
        if latest_scored_at:
            try:
                gaps_str = str(gaps_computed_at).replace("Z", "+00:00")
                gaps_dt = datetime.fromisoformat(gaps_str)
                score_str = str(latest_scored_at).replace("Z", "+00:00")
                score_dt = datetime.fromisoformat(score_str)
                gaps_stale = score_dt > gaps_dt
            except Exception:
                gaps_stale = False
        else:
            gaps_stale = False

    return SystemState(
        last_fetch_at=last_fetch_at,
        hours_since_fetch=hours_since_fetch,
        unscored_count=unscored_count,
        gaps_computed_at=gaps_computed_at,
        gaps_stale=gaps_stale,
        last_cycle_verdict=metrics.get("last_cycle_verdict"),
        last_cycle_at=metrics.get("last_cycle_at"),
    )
