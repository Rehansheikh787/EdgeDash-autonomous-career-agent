from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.config import Config, load_config


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS", "WARN", "FAIL"
    observed: str
    message: str


@dataclass
class HealthStatus:
    is_healthy: bool
    overall_status: str  # "healthy", "stale", "degraded"
    summary_line: str
    checks: list[CheckResult]


def check_health(
    db_path: str = "edgedash.db",
    config: Config | None = None,
    now: datetime | None = None,
) -> HealthStatus:
    """Evaluate 4 system health criteria against the active database (Rule 50 safe)."""
    cfg = config or load_config()
    curr_dt = now or datetime.now(timezone.utc)
    checks: list[CheckResult] = []

    # ── Check 1: Database Reachability ────────────────────────────────
    db_connected = False
    try:
        metrics = storage.read_system_state_metrics(db_path)
        db_connected = True
        backend_name = "PostgreSQL" if storage.is_postgres() else "SQLite"
        checks.append(
            CheckResult(
                name="Database Connectivity",
                status="PASS",
                observed=f"Connected ({backend_name})",
                message="Database is responsive and accessible.",
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult(
                name="Database Connectivity",
                status="FAIL",
                observed="Unreachable / Error",
                message=f"Failed to query database: {exc}",
            )
        )
        return HealthStatus(
            is_healthy=False,
            overall_status="degraded",
            summary_line="🔴 Database unreachable",
            checks=checks,
        )

    # ── Check 2: Listing Freshness (Newest listing <= 3.0 days) ───────
    last_fetch_str = metrics.get("last_fetch_at") or storage.last_fetch_time(db_path)
    if last_fetch_str:
        try:
            clean_ts = str(last_fetch_str).replace("Z", "+00:00")
            fetch_dt = datetime.fromisoformat(clean_ts)
            if fetch_dt.tzinfo is None:
                fetch_dt = fetch_dt.replace(tzinfo=timezone.utc)
            age_days = max(0.0, (curr_dt - fetch_dt).total_seconds() / 86400.0)

            if age_days <= 3.0:
                checks.append(
                    CheckResult(
                        name="Listing Freshness",
                        status="PASS",
                        observed=f"{age_days:.1f}d ago (ts: {str(last_fetch_str)[:19]})",
                        message="Newest listing is within the 3.0-day freshness window.",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="Listing Freshness",
                        status="FAIL",
                        observed=f"{age_days:.1f}d ago (threshold: <= 3.0d)",
                        message="Market data is stale — newest listing exceeds 3 days.",
                    )
                )
        except Exception:
            checks.append(
                CheckResult(
                    name="Listing Freshness",
                    status="FAIL",
                    observed=f"Invalid timestamp: {last_fetch_str}",
                    message="Could not parse newest listing timestamp.",
                )
            )
    else:
        checks.append(
            CheckResult(
                name="Listing Freshness",
                status="WARN",
                observed="No listings in database",
                message="Initial data ingestion has not populated listings yet.",
            )
        )

    # ── Check 3: Recent Successful Cycle (Passing cycle in last 48h) ───
    verified_cycle = storage.get_latest_verified_cycle(db_path)
    hours_since_pass: float | None = None
    if verified_cycle and verified_cycle.get("finished_at"):
        try:
            v_ts = str(verified_cycle["finished_at"]).replace("Z", "+00:00")
            v_dt = datetime.fromisoformat(v_ts)
            if v_dt.tzinfo is None:
                v_dt = v_dt.replace(tzinfo=timezone.utc)
            hours_since_pass = max(0.0, (curr_dt - v_dt).total_seconds() / 3600.0)

            if hours_since_pass <= 48.0:
                checks.append(
                    CheckResult(
                        name="Successful Cycle Recency",
                        status="PASS",
                        observed=f"{hours_since_pass:.1f}h ago (verdict: verified)",
                        message="Passing cycle recorded within the 48-hour threshold.",
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        name="Successful Cycle Recency",
                        status="FAIL",
                        observed=f"{hours_since_pass:.1f}h ago (threshold: <= 48.0h)",
                        message="No passing cycle recorded in the last 48 hours.",
                    )
                )
        except Exception:
            checks.append(
                CheckResult(
                    name="Successful Cycle Recency",
                    status="FAIL",
                    observed=f"Invalid timestamp: {verified_cycle.get('finished_at')}",
                    message="Could not parse verified cycle timestamp.",
                )
            )
    else:
        checks.append(
            CheckResult(
                name="Successful Cycle Recency",
                status="WARN",
                observed="No verified cycles recorded yet",
                message="Waiting for initial cycle completion.",
            )
        )

    # ── Check 4: Last 3 Cycles Verification Failure Check ─────────────
    recent_logs = storage.get_recent_cycle_logs(db_path, limit=3)
    failed_count = sum(
        1 for r in recent_logs if r.get("status") in ("failed", "degraded")
    )
    if len(recent_logs) >= 3 and failed_count >= 3:
        checks.append(
            CheckResult(
                name="Cycle Failure Sequence",
                status="FAIL",
                observed=f"3 of 3 consecutive failures ({[r.get('status') for r in recent_logs]})",
                message="Last 3 cycles all failed verification.",
            )
        )
    else:
        obs_str = f"{failed_count} of {len(recent_logs)} recent cycles failed"
        checks.append(
            CheckResult(
                name="Cycle Failure Sequence",
                status="PASS",
                observed=obs_str,
                message="No consecutive 3-cycle verification failure detected.",
            )
        )

    # ── Determine Overall Status ──────────────────────────────────────
    has_fails = any(c.status == "FAIL" for c in checks)
    is_healthy = not has_fails

    if has_fails or (len(recent_logs) >= 3 and failed_count >= 3):
        overall_status = "degraded"
        summary_line = "[DEGRADED] System Attention Required: Recent cycle or database verification issues"
    elif hours_since_pass is not None and hours_since_pass > 24.0:
        overall_status = "stale"
        summary_line = f"[STALE] System Active (Stale Data): Last verified cycle was {hours_since_pass:.1f}h ago"
    elif hours_since_pass is not None:
        overall_status = "healthy"
        summary_line = f"[HEALTHY] System Operational: Live verified data from {hours_since_pass:.1f}h ago"
    else:
        overall_status = "stale"
        summary_line = "[INITIALIZING] System Active: Waiting for initial automated collection cycle"

    return HealthStatus(
        is_healthy=is_healthy,
        overall_status=overall_status,
        summary_line=summary_line,
        checks=checks,
    )


def main() -> None:
    print("\n" + "=" * 60)
    print("  EdgeDash System Health Diagnostics")
    print("=" * 60 + "\n")

    health = check_health()

    for c in health.checks:
        status_tag = f"[{c.status}]"
        print(f"  {status_tag:<8} {c.name:<26} : {c.observed}")
        if c.status == "FAIL":
            print(f"           -> Reason: {c.message}")

    print("\n" + "-" * 60)
    print(f"  Summary: {health.summary_line}")
    print("-" * 60 + "\n")

    if not health.is_healthy:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
