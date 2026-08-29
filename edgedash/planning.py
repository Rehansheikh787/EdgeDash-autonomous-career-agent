from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edgedash.config import Config
from edgedash.state import SystemState


@dataclass(frozen=True)
class Task:
    """Explicit delegation of a single task to an agent (Rule 29, 31)."""
    agent_name: str
    action: str  # "run" | "skip"
    goal: str
    stop_conditions: dict[str, Any]
    reason: str


@dataclass(frozen=True)
class Plan:
    """Ordered execution plan composed of explicit tasks (Rule 28, 31)."""
    tasks: list[Task] = field(default_factory=list)

    def render(self) -> str:
        """Render compact printable plan before execution (Rule 31)."""
        lines = [
            "  Plan",
            "  " + "-" * 66,
        ]
        for t in self.tasks:
            icon = ">" if t.action == "run" else "-"
            action_tag = "RUN " if t.action == "run" else "SKIP"
            limits_str = ", ".join(f"{k}={v}" for k, v in t.stop_conditions.items())
            lines.append(f"  {icon} {t.agent_name:<12} [{action_tag}] {t.reason}")
            lines.append(f"      Goal: {t.goal} | Limits: ({limits_str})")
        return "\n".join(lines)


def build_plan(state: SystemState, config: Config) -> Plan:
    """Pure function calculating deterministic execution plan from state and config (Rule 28)."""
    tasks: list[Task] = []

    # ── 1. Fetcher Decision ───────────────────────────────────────────
    fetch_interval = getattr(config, "fetch_interval_hours", 6.0)
    if state.hours_since_fetch is None:
        fetch_run = True
        fetch_reason = f"hours_since_fetch=never >= {fetch_interval:.1f}h"
    elif state.hours_since_fetch >= fetch_interval:
        fetch_run = True
        fetch_reason = f"hours_since_fetch={state.hours_since_fetch:.1f}h >= {fetch_interval:.1f}h"
    else:
        fetch_run = False
        fetch_reason = f"skipped: hours_since_fetch={state.hours_since_fetch:.1f}h < {fetch_interval:.1f}h"

    tasks.append(
        Task(
            agent_name="Fetcher",
            action="run" if fetch_run else "skip",
            goal="fetch new job listings from enabled sources",
            stop_conditions={
                "max_pages": getattr(config, "max_fetch_pages", 5),
                "max_listings": getattr(config, "max_fetch_listings", 100),
            },
            reason=fetch_reason,
        )
    )

    # ── 2. Scorer Decision ────────────────────────────────────────────
    if state.unscored_count > 0:
        score_run = True
        score_reason = f"unscored_count={state.unscored_count}"
    else:
        score_run = False
        score_reason = "skipped: unscored_count=0"

    tasks.append(
        Task(
            agent_name="Scorer",
            action="run" if score_run else "skip",
            goal=f"score up to {getattr(config, 'score_batch_size', 25)} unscored listings",
            stop_conditions={
                "max_items": getattr(config, "score_batch_size", 25),
                "max_seconds": getattr(config, "score_max_seconds", 120),
            },
            reason=score_reason,
        )
    )

    # ── 3. GapAnalyzer Decision ───────────────────────────────────────
    if state.gaps_computed_at is None:
        gap_run = True
        gap_reason = "gaps_computed_at is null"
    elif state.gaps_stale:
        gap_run = True
        gap_reason = "gaps_stale=True"
    elif state.last_cycle_verdict not in ("complete", "verified"):
        gap_run = True
        gap_reason = f"last_cycle_verdict={state.last_cycle_verdict} (re-analyze)"
    else:
        gap_run = False
        gap_reason = "skipped: gaps_stale=False"

    tasks.append(
        Task(
            agent_name="GapAnalyzer",
            action="run" if gap_run else "skip",
            goal="compute snapshot of skill gaps and opportunity costs",
            stop_conditions={
                "max_seconds": getattr(config, "gap_max_seconds", 30),
            },
            reason=gap_reason,
        )
    )

    # ── 4. Verifier Decision ──────────────────────────────────────────
    any_upstream_run = fetch_run or score_run or gap_run
    if any_upstream_run:
        verify_run = True
        verify_reason = "audit output plausibility of cycle"
    elif state.last_cycle_verdict not in ("complete", "verified"):
        verify_run = True
        verify_reason = f"last_cycle_verdict={state.last_cycle_verdict} (re-verify)"
    else:
        verify_run = False
        verify_reason = "skipped: no new cycle mutations to verify"

    tasks.append(
        Task(
            agent_name="Verifier",
            action="run" if verify_run else "skip",
            goal="audit output plausibility across score spread, extractions, gaps, and freshness",
            stop_conditions={
                "max_seconds": 30,
            },
            reason=verify_reason,
        )
    )

    return Plan(tasks=tasks)

