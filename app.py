from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from edgedash import storage
from edgedash.config import load_config

logger = logging.getLogger("edgedash.app")

# ── Page Configuration & Theming ──────────────────────────────────────
st.set_page_config(
    page_title="EdgeDash — Career Intelligence Agent",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Custom styling for high readability and visual distinction
st.markdown(
    """
    <style>
    .metric-card {
        background-color: #1e222d;
        border-radius: 8px;
        padding: 14px 18px;
        border: 1px solid #2d3343;
    }
    .footer-text {
        color: #94a3b8;
        font-size: 0.85rem;
        text-align: center;
        padding: 24px 0 10px 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── Cached Storage Readers (Short TTL, Rule 50 Error Boundary) ─────────
@st.cache_data(ttl=10)
def _get_config():
    return load_config()


def _read_data(db_path: str) -> dict[str, Any] | None:
    """Read data snapshot from storage with robust error handling (Rule 2, 38, 50)."""
    try:
        storage.init_db(db_path)
        return {
            "latest_cycle": storage.get_latest_cycle(db_path),
            "latest_verified": storage.get_latest_verified_cycle(db_path),
            "recent_logs": storage.get_recent_cycle_logs(db_path, limit=30),
            "scored_listings": storage.get_scored_listings(db_path),
            "gap_snapshot": storage.get_latest_gap_snapshot(db_path),
            "metrics": storage.read_system_state_metrics(db_path),
        }
    except Exception as exc:
        logger.error("Failed to read data from database: %s", exc, exc_info=True)
        return None


def main() -> None:
    config = _get_config()
    db_path = config.db_path

    st.title("⚡ EdgeDash — Career Intelligence Agent")

    data = _read_data(db_path)

    # ── Rule 50: Hostile Startup / Unreachable Database ───────────────
    if data is None:
        st.warning(
            "⚠️ **Database Status:** Unable to reach the database right now. "
            "If this is a new deployment, the scheduled data cycle will populate it shortly."
        )
        _render_footer(None)
        return

    latest_cycle = data.get("latest_cycle")
    latest_verified = data.get("latest_verified")
    recent_logs = data.get("recent_logs") or []
    scored_listings = data.get("scored_listings") or []
    gap_snapshot = data.get("gap_snapshot")
    metrics = data.get("metrics") or {}

    verified_ts = latest_verified.get("finished_at") if latest_verified else None
    latest_ts = latest_cycle.get("finished_at") if latest_cycle else None
    current_verdict = latest_cycle.get("status", "unknown") if latest_cycle else "none"

    # ── Rule 50: Empty Database / No Cycles Yet ───────────────────────
    if not recent_logs and not scored_listings:
        st.info(
            "ℹ️ **No cycles yet — the first automated collection run is scheduled soon.** "
            "Once the first autonomous cycle completes, verified job matches and skill gaps will appear here."
        )
        _render_footer(verified_ts)
        return

    # ── 1. Header Strip ───────────────────────────────────────────────
    try:
        total_listings = metrics.get("scored_count", 0) + metrics.get("unscored_count", 0)
        total_scored = len(scored_listings)

        # Warning banner if newest cycle failed/degraded (Rule 38)
        if latest_cycle and latest_cycle.get("status") in ("failed", "degraded", "partial"):
            v_time_str = verified_ts or "None recorded"
            st.warning(
                f"⚠️ **Stale Verified Data In Use (Rule 38):** "
                f"The newest cycle at `{latest_ts}` concluded with status `{current_verdict}`. "
                f"Listings and skill gap panels below are preserved from the last passing verified cycle at `{v_time_str}`."
            )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric(
                label="Last Passing Cycle",
                value=_format_time(verified_ts),
                help="Timestamp of the most recent cycle with a passing/verified verdict (Rule 38).",
            )
        with c2:
            st.metric(label="Total Database Listings", value=total_listings)
        with c3:
            st.metric(label="Total Scored Listings", value=total_scored)
        with c4:
            st.metric(
                label="Latest Cycle Status",
                value=current_verdict.upper(),
                delta="PASSING" if current_verdict in ("complete", "verified") else "ATTENTION REQUIRED",
                delta_color="normal" if current_verdict in ("complete", "verified") else "inverse",
            )
    except Exception as exc:
        logger.error("Error rendering header metrics: %s", exc, exc_info=True)
        st.error("Header metrics temporarily unavailable.")

    st.markdown("---")

    # ── 2. ASK YOUR DATA (Natural Language Queries — Rules 40-46) ─────
    try:
        st.subheader("💬 Ask Your Career Data")
        st.caption(
            "Ask questions in plain English. Verified answers backed by deterministic query tools and underlying data (Rules 40–46)."
        )

        daily_queries = storage.get_daily_query_count(db_path)
        if daily_queries >= config.max_daily_queries:
            st.warning(
                f"ℹ️ **Daily Query Cap Reached ({daily_queries}/{config.max_daily_queries}):** "
                "Natural language questions are paused for the day to prevent quota exhaustion. "
                "All data panels below remain fully functional."
            )
        else:
            col_btn1, col_btn2, col_btn3 = st.columns(3)
            selected_example = None
            with col_btn1:
                if st.button("🎯 What are my best matches?", use_container_width=True):
                    selected_example = "What are my best matching jobs?"
            with col_btn2:
                if st.button("🏢 Which companies are hiring?", use_container_width=True):
                    selected_example = "Which companies are hiring right now?"
            with col_btn3:
                if st.button("📊 What are my top skill gaps?", use_container_width=True):
                    selected_example = "What are the biggest skill gaps in the market?"

            if "session_id" not in st.session_state:
                import uuid
                st.session_state["session_id"] = str(uuid.uuid4())[:8]

            query_input = st.text_input(
                "Enter your question (max 300 characters):",
                value=selected_example or "",
                placeholder="e.g., Which companies posted jobs in the last 7 days?",
                key="nl_query_input",
            )

            if st.button("Ask EdgeDash", type="primary", use_container_width=False) or selected_example:
                if query_input.strip():
                    with st.spinner("Analyzing verified database..."):
                        from edgedash.query.ask import ask
                        answer = ask(
                            query_input,
                            session_id=st.session_state["session_id"],
                            config=config,
                            db_path=db_path,
                        )

                    if answer.answerable:
                        st.success(f"**Answer:** {answer.text}")
                        if answer.summary:
                            st.caption(f"ℹ️ {answer.summary} · Tool used: `{answer.tool_used}`")
                        
                        # Rule 44: Display underlying data rows alongside prose answer
                        if answer.rows:
                            with st.expander("🔍 View Underlying Verified Rows (Rule 44)", expanded=True):
                                st.dataframe(answer.rows, use_container_width=True)
                    else:
                        st.info(answer.text)
                else:
                    st.warning("Please enter a question first.")
    except Exception as exc:
        logger.error("Error in Ask Your Data panel: %s", exc, exc_info=True)
        st.info("Ask Your Data panel is temporarily initializing.")

    st.markdown("---")

    # ── 3. AGENT ACTIVITY LOG (Recent 30 cycles) ──────────────────────
    try:
        st.subheader("📋 Agent Activity Log (Recent 30 Cycles)")
        st.caption("Complete chronological record of all autonomous cycles, agent executions, and verification verdicts.")

        log_rows: list[dict[str, Any]] = []
        for row in recent_logs:
            status_val = row.get("status", "unknown")
            started = row.get("started_at", "")
            finished = row.get("finished_at", "")
            duration_sec = _calc_duration(started, finished)

            status_emoji = {
                "complete": "🟢 complete",
                "verified": "🟢 verified",
                "ok": "🟢 ok",
                "nothing_to_do": "⚪ nothing_to_do",
                "degraded": "🔴 DEGRADED",
                "failed": "❌ FAILED",
                "partial": "🟡 partial",
                "skipped": "⚪ skipped",
            }.get(status_val, status_val)

            log_rows.append({
                "Timestamp": _format_time(finished),
                "Agent": row.get("agent", "Unknown"),
                "Verdict / Status": status_emoji,
                "Records Touched": row.get("records_touched", 0),
                "Duration": f"{duration_sec:.1f}s" if duration_sec is not None else "—",
                "Notes / Observed Verdict": row.get("notes", ""),
            })

        if log_rows:
            st.dataframe(
                log_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Timestamp": st.column_config.TextColumn("Timestamp", width="medium"),
                    "Agent": st.column_config.TextColumn("Agent", width="small"),
                    "Verdict / Status": st.column_config.TextColumn("Verdict / Status", width="small"),
                    "Records Touched": st.column_config.NumberColumn("Records", width="small"),
                    "Duration": st.column_config.TextColumn("Duration", width="small"),
                    "Notes / Observed Verdict": st.column_config.TextColumn("Details / Reason / Verifier Checks", width="large"),
                },
            )
        else:
            st.info("No activity logged yet.")
    except Exception as exc:
        logger.error("Error in Agent Activity Log: %s", exc, exc_info=True)
        st.info("Activity log is temporarily unavailable.")

    st.markdown("---")

    # ── 4. Two Compact Panels (Top 10 Listings & Top 10 Gaps) ─────────
    col_left, col_right = st.columns([1.1, 0.9])

    with col_left:
        try:
            st.subheader("🎯 Top 10 Scored Listings (Verified)")
            st.caption("Ranked by deterministic multi-component fit score (0–100).")

            top_10_listings = scored_listings[:10]
            if top_10_listings:
                for item in top_10_listings:
                    score = item.get("fit_score", 0)
                    title = item.get("title", "Untitled")
                    company = item.get("company", "Unknown")
                    location = item.get("location", "")
                    reason = item.get("fit_reason", "No reason recorded")
                    url = item.get("url", "")

                    score_color = "🟢" if score >= 70 else ("🟡" if score >= 45 else "⚪")

                    with st.expander(f"{score_color} **[{score}/100]** {title} — *{company}* ({location})"):
                        st.write(f"**Fit Breakdown & Gaps:** {reason}")
                        if url:
                            st.markdown(f"[View Job Posting ↗]({url})")
            else:
                st.info("No scored listings available yet.")
        except Exception as exc:
            logger.error("Error in Scored Listings panel: %s", exc, exc_info=True)
            st.info("Scored listings temporarily unavailable.")

    with col_right:
        try:
            st.subheader("📊 Top 10 Market Skill Gaps (Rule 24, 25)")
            st.caption("Weighted by opportunity cost $\\sum(\\text{fit\\_score}/100)$ from verified snapshot.")

            if isinstance(gap_snapshot, list):
                gaps = gap_snapshot
                snap_run_id = gaps[0].get("run_id", "latest") if gaps else "unknown"
                snap_sample_size = gaps[0].get("sample_size", len(scored_listings)) if gaps else 0
            elif isinstance(gap_snapshot, dict):
                gaps = gap_snapshot.get("gaps", [])
                snap_run_id = gap_snapshot.get("run_id", "latest")
                snap_sample_size = gap_snapshot.get("sample_size", len(scored_listings))
            else:
                gaps = []
                snap_run_id = "none"
                snap_sample_size = 0

            if gaps:
                gap_display: list[dict[str, Any]] = []
                for rank, g in enumerate(gaps[:10], start=1):
                    gap_display.append({
                        "#": rank,
                        "Missing Skill": g.get("skill", ""),
                        "Blocked": g.get("listings_blocked", 0),
                        "Opp. Cost": f"{g.get('opportunity_cost', 0):.2f}",
                        "Mean Score": f"{g.get('mean_score', 0):.1f}",
                        "Confidence": f"⚠️ {g.get('confidence')}" if g.get("confidence") == "low" else "✅ high",
                    })

                st.dataframe(gap_display, use_container_width=True, hide_index=True)
                st.caption(
                    f"Snapshot: `{snap_run_id}` · "
                    f"Sample size: {snap_sample_size} listing(s)"
                )
            else:
                st.info("No skill gaps snapshot recorded yet.")
        except Exception as exc:
            logger.error("Error in Skill Gaps panel: %s", exc, exc_info=True)
            st.info("Skill gaps temporarily unavailable.")

    _render_footer(verified_ts)


# ── Footer & Helpers ──────────────────────────────────────────────────


def _render_footer(verified_ts: str | None) -> None:
    st.markdown("---")
    ts_str = _format_time(verified_ts) if verified_ts else "Pending initial cycle"
    st.markdown(
        f'<div class="footer-text">'
        f"⚡ <strong>EdgeDash</strong> · Last Verified Cycle: <code>{ts_str}</code> · "
        f'<a href="https://github.com/Rehansheikh787/EdgeDash-autonomous-career-agent-" target="_blank" style="color: #60a5fa; text-decoration: none;">GitHub Repository ↗</a>'
        f"</div>",
        unsafe_allow_html=True,
    )


def _format_time(iso_str: str | None) -> str:
    if not iso_str:
        return "Never"
    try:
        clean_str = str(iso_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(iso_str)[:19]


def _calc_duration(start_str: str, finish_str: str) -> float | None:
    if not start_str or not finish_str:
        return None
    try:
        s_clean = str(start_str).replace("Z", "+00:00")
        f_clean = str(finish_str).replace("Z", "+00:00")
        s_dt = datetime.fromisoformat(s_clean)
        f_dt = datetime.fromisoformat(f_clean)
        return max(0.0, (f_dt - s_dt).total_seconds())
    except Exception:
        return None


if __name__ == "__main__":
    main()
