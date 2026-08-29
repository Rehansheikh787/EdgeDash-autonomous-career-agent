from __future__ import annotations

import sys
from typing import Any

from edgedash import storage
from edgedash.config import load_config


def show_gaps() -> None:
    config = load_config()
    db_path = config.db_path
    storage.init_db(db_path)

    gaps = storage.get_latest_gap_snapshot(db_path)

    print("\n" + "═" * 74)
    print("  EdgeDash — Career Intelligence Skill Gaps Report")
    print("═" * 74)

    if not gaps:
        print("\n  (No skill gaps snapshots found in database yet.)")
        print("  Run 'python -X utf8 run_cycle.py' to score listings and generate gap reports.\n")
        return

    first = gaps[0]
    run_id = first.get("run_id", "unknown")
    computed_at = first.get("computed_at", "unknown")
    sample_size = first.get("sample_size", 0)

    print(f"  Snapshot Run : {run_id}")
    print(f"  Computed At  : {computed_at}")
    print(f"  Sample Size  : {sample_size} scored listing(s) analyzed")
    print("  " + "─" * 70)
    print(f"  {'#':<3} {'Missing Skill':<18} {'Blocked':<8} {'Opp. Cost':<10} {'Mean Score':<11} {'Impact Bar'}")
    print("  " + "─" * 70)

    max_cost = max((float(g.get("opportunity_cost", 0)) for g in gaps), default=1.0) or 1.0

    for idx, item in enumerate(gaps, 1):
        skill = item["skill"]
        blocked = item["listings_blocked"]
        cost = float(item["opportunity_cost"])
        mean_s = float(item["mean_score"])
        conf = item.get("confidence", "high")

        bar_len = int(round((cost / max_cost) * 16))
        bar = "█" * max(1, bar_len)

        conf_flag = " ⚠️ low conf" if conf == "low" else ""
        print(f"  {idx:<3} {skill:<18} {blocked:<8} {cost:<10.2f} {mean_s:<11.1f} {bar}{conf_flag}")

    # Drill-down section (Rule 26)
    print("\n  Top Gaps Traceability (Listing IDs to Inspect)")
    print("  " + "─" * 70)
    for idx, item in enumerate(gaps[:3], 1):
        ex_ids = item.get("example_ids") or []
        ex_str = ", ".join(ex_ids[:3]) if ex_ids else "none"
        print(f"  {idx}. {item['skill']} (blocked {item['listings_blocked']} listings):")
        print(f"     Top blocked IDs: {ex_str}")

    print("\n" + "═" * 74 + "\n")


def show_trend() -> None:
    config = load_config()
    db_path = config.db_path
    storage.init_db(db_path)

    runs = storage.get_gap_snapshot_runs(db_path)

    print("\n" + "═" * 78)
    print("  EdgeDash — Skill Gaps Trend Over Time (Rule 25)")
    print("═" * 78)

    if not runs:
        print("\n  (No snapshots recorded yet.)")
        print("  Run 'python -X utf8 run_cycle.py' to produce your first snapshot.\n")
        return

    if len(runs) == 1:
        single = runs[0]
        print(f"\n  ℹ️  Only 1 snapshot recorded so far ({single['computed_at']}).")
        print(f"     Sample size: {single['sample_size']} listings.")
        print("\n  At least 2 separate scheduled cycle runs are needed to measure trends.")
        print("  Trend metrics are never fabricated, interpolated, or guessed from one point.\n")
        print("═" * 78 + "\n")
        return

    earliest_meta = runs[0]
    latest_meta = runs[-1]

    earliest_records = storage.get_gap_snapshot_by_run(db_path, earliest_meta["run_id"])
    latest_records = storage.get_gap_snapshot_by_run(db_path, latest_meta["run_id"])

    earliest_map = {r["skill"]: float(r["opportunity_cost"]) for r in earliest_records}
    earliest_top_skills = {r["skill"] for r in earliest_records[:10]}

    print(f"  Comparison Window : {len(runs)} snapshots total")
    print(f"  Earliest Snapshot : {earliest_meta['computed_at']} (N={earliest_meta['sample_size']})")
    print(f"  Latest Snapshot   : {latest_meta['computed_at']} (N={latest_meta['sample_size']})")
    print("  " + "─" * 74)
    print(f"  {'#':<3} {'Skill':<18} {'Earliest':<10} {'Latest':<10} {'Abs Change':<12} {'% Change'}")
    print("  " + "─" * 74)

    latest_top_skills: set[str] = set()

    for idx, item in enumerate(latest_records[:10], 1):
        skill = item["skill"]
        latest_top_skills.add(skill)
        latest_cost = float(item["opportunity_cost"])

        if skill in earliest_map:
            early_cost = earliest_map[skill]
            diff_abs = latest_cost - early_cost
            if early_cost > 0:
                diff_pct = (diff_abs / early_cost) * 100.0
                pct_str = f"{diff_pct:+.1f}%"
            else:
                pct_str = "n/a"

            sign = "+" if diff_abs > 0 else ""
            change_abs_str = f"{sign}{diff_abs:.2f}"
            early_str = f"{early_cost:.2f}"
        else:
            early_str = "—"
            change_abs_str = "NEW"
            pct_str = "NEW"

        print(f"  {idx:<3} {skill:<18} {early_str:<10} {latest_cost:<10.2f} {change_abs_str:<12} {pct_str}")

    # Dropped out skills (were in earliest top 10, now absent from latest top 10)
    dropped_out = earliest_top_skills - latest_top_skills
    if dropped_out:
        print("\n  Dropped Out of Top 10:")
        print("  " + "─" * 74)
        for skill in sorted(dropped_out):
            old_cost = earliest_map.get(skill, 0.0)
            print(f"  • {skill:<18} (previous cost: {old_cost:.2f}) → DROPPED OUT")

    print("\n" + "═" * 78 + "\n")


if __name__ == "__main__":
    if "--trend" in sys.argv:
        show_trend()
    else:
        show_gaps()
