from __future__ import annotations

import time
from datetime import datetime, timezone

from edgedash import storage
from edgedash.agents.base import Agent, AgentResult
from edgedash.agents.fetcher import Fetcher
from edgedash.agents.gap_analyzer import GapAnalyzer
from edgedash.agents.mock_fetcher import MockFetcher
from edgedash.agents.scorer import Scorer
from edgedash.agents.verifier import Verifier
from edgedash.config import Config
from edgedash.planning import Task, build_plan
from edgedash.state import read_state


def run_cycle(config: Config) -> None:
    """Run one state-driven autonomous cycle with verification and retry (Rules 28-39)."""
    db = config.db_path
    storage.init_db(db)
    cycle_start_dt = datetime.now(timezone.utc)

    # ── 1. Read State & Build Plan (Rule 28) ──────────────────────────
    state = read_state(config, now=cycle_start_dt)
    plan = build_plan(state, config)

    _header()
    _show_state(state)

    # ── 2. Print Rendered Plan (Rule 31) ──────────────────────────────
    print(plan.render())
    print()

    # ── 3. Check "Nothing to do" Condition (Rule 28, 33) ──────────────
    runnable_tasks = [t for t in plan.tasks if t.action == "run"]
    skipped_tasks = [t for t in plan.tasks if t.action == "skip"]

    if not runnable_tasks:
        print("  ✓ State optimal — no tasks required this cycle (nothing to do).")
        print("\n" + "═" * 48 + "\n")
        storage.log_cycle(
            db,
            agent="Orchestrator",
            started_at=cycle_start_dt.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            records_touched=0,
            status="nothing_to_do",
            notes="all tasks skipped: system state optimal",
        )
        return

    # ── 4. Agent Registry (Resolved by name) ──────────────────────────
    fetcher: Agent = MockFetcher() if config.use_mock_fetcher else Fetcher()
    registry: dict[str, Agent] = {
        "Fetcher": fetcher,
        "MockFetcher": fetcher,
        "Scorer": Scorer(),
        "GapAnalyzer": GapAnalyzer(),
        "Verifier": Verifier(),
    }

    # ── 5. Execute Planned Tasks (Rule 29, 32) ─────────────────────────
    print("  Running planned agents …")
    print("  " + "─" * 44)

    results: list[tuple[Task, AgentResult, float]] = []
    any_failed = False
    total_records = 0
    verifier_result: AgentResult | None = None
    retry_count = 0
    failed_checks_str = "none"

    for task in plan.tasks:
        if task.action == "skip":
            print(f"  · {task.agent_name:<14} [SKIPPED] {task.reason}")
            continue

        agent = registry.get(task.agent_name)
        if not agent:
            err_msg = f"No registered agent for task '{task.agent_name}'"
            print(f"  ✗ {task.agent_name:<14} [FAILED]  {err_msg}")
            any_failed = True
            continue

        t0 = time.monotonic()
        task_started = datetime.now(timezone.utc)

        # Rule 32: Try/except per sub-agent so one failure never stops the cycle
        try:
            result = agent.run(config, db, stop_conditions=task.stop_conditions)
            if result.status == "failed":
                any_failed = True
        except Exception as exc:
            result = AgentResult(agent.name, "failed", 0, str(exc))
            any_failed = True

        elapsed = time.monotonic() - t0
        task_finished = datetime.now(timezone.utc)
        total_records += result.records_touched

        mark = "✓" if result.status == "ok" else "✗"
        print(f"  {mark} {agent.name:<14} {result.status:<8} {result.notes}")

        storage.log_cycle(
            db,
            agent=agent.name,
            started_at=task_started.isoformat(),
            finished_at=task_finished.isoformat(),
            records_touched=result.records_touched,
            status=result.status,
            notes=result.notes,
        )
        results.append((task, result, elapsed))

        if task.agent_name == "Verifier":
            verifier_result = result

    # ── 6. Verification Retry Handling (Rule 36) ──────────────────────
    is_degraded = False
    if verifier_result and verifier_result.status == "failed":
        failed_checks_str = verifier_result.notes
        print()
        print("  ⚠️  Verification failed — initiating single retry with adjusted context (Rule 36)…")
        retry_count = 1

        # Determine if failure relates to score distribution
        is_score_failure = "score_spread" in verifier_result.notes

        if is_score_failure:
            print("  ▸ Retrying Scorer with widen_distribution=True…")
            scorer_agent = registry["Scorer"]
            try:
                scorer_res = scorer_agent.run(
                    config, db, stop_conditions={"widen_distribution": True, "max_items": config.score_batch_size}
                )
                print(f"    ✓ Scorer retry {scorer_res.status:<8} {scorer_res.notes}")
                # Re-run GapAnalyzer with adjusted scores
                gap_agent = registry["GapAnalyzer"]
                gap_res = gap_agent.run(config, db, stop_conditions={"max_seconds": config.gap_max_seconds})
                print(f"    ✓ GapAnalyzer   {gap_res.status:<8} {gap_res.notes}")
            except Exception as exc:
                print(f"    ✗ Scorer retry failed: {exc}")

        # Final re-verification pass
        print("  ▸ Re-running Verifier…")
        verifier_agent = registry["Verifier"]
        try:
            verifier_result = verifier_agent.run(config, db)
            mark = "✓" if verifier_result.status == "ok" else "✗"
            print(f"    {mark} Verifier (final) {verifier_result.status:<8} {verifier_result.notes}")
            if verifier_result.status == "failed":
                is_degraded = True
                failed_checks_str = verifier_result.notes
                print("  ✗ Final verification failed — marking cycle as degraded (Rule 36).")
            else:
                is_degraded = False
                failed_checks_str = "passed on retry"
        except Exception as exc:
            is_degraded = True
            failed_checks_str = f"Verifier exception: {exc}"
            print(f"    ✗ Verifier retry crashed: {exc}")

    # ── 7. Cycle Outcome Resolution (Rule 33, 36) ──────────────────────
    if is_degraded:
        cycle_outcome = "degraded"
    elif any_failed:
        cycle_outcome = "partial"
    else:
        cycle_outcome = "complete"

    ran_names = [t.agent_name for t, _, _ in results]
    skipped_summary = [f"{t.agent_name}: {t.reason}" for t in skipped_tasks]
    duration_summary = [f"{t.agent_name}={elapsed:.1f}s" for t, _, elapsed in results]

    storage.log_cycle(
        db,
        agent="Orchestrator",
        started_at=cycle_start_dt.isoformat(),
        finished_at=datetime.now(timezone.utc).isoformat(),
        records_touched=total_records,
        status=cycle_outcome,
        notes=(
            f"outcome={cycle_outcome} | retries={retry_count} | "
            f"failed_checks=[{failed_checks_str}] | "
            f"ran=[{', '.join(ran_names)}] | "
            f"skipped=[{'; '.join(skipped_summary)}] | "
            f"durations=[{', '.join(duration_summary)}]"
        ),
    )

    print()
    _show_summary(results, skipped_tasks)
    _footer(len(results), total_records, cycle_outcome)


# ── display helpers ───────────────────────────────────────────────


def _header() -> None:
    print()
    print("=" * 48)
    print("  EdgeDash - State-Driven Cycle Start")
    print("=" * 48)
    print()


def _show_state(state: Any) -> None:
    hours_str = f"{state.hours_since_fetch:.1f}h ago" if state.hours_since_fetch is not None else "never"
    print("  State")
    print("  " + "-" * 44)
    print(f"  Last fetch     : {state.last_fetch_at or 'never'} ({hours_str})")
    print(f"  Unscored       : {state.unscored_count}")
    print(f"  Gaps computed  : {state.gaps_computed_at or 'never'} (stale={state.gaps_stale})")
    print(f"  Last verdict   : {state.last_cycle_verdict or 'none'}")
    print()


def _show_summary(
    results: list[tuple[Task, AgentResult, float]],
    skipped_tasks: list[Task],
) -> None:
    print("  Summary")
    print("  " + "-" * 44)
    print(f"  {'Agent':<15} {'Status':<10} {'Records':<9} Time")
    for _, res, elapsed in results:
        print(f"  {res.agent:<15} {res.status:<10} {res.records_touched:<9} {elapsed:.2f}s")
    for t in skipped_tasks:
        print(f"  {t.agent_name:<15} {'skipped':<10} {'0':<9} 0.00s")
    print()


def _footer(ran_count: int, touched: int, outcome: str) -> None:
    print("=" * 48)
    print(f"  Cycle {outcome} - {ran_count} agent(s) ran, {touched} records touched")
    print("=" * 48)
    print()
