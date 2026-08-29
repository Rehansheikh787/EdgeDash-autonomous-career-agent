from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.verification import Verdict, run_all_checks


class Verifier:
    """Deterministic Verifier agent auditing output plausibility (Rules 34-39)."""

    @property
    def name(self) -> str:
        return "Verifier"

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        now = datetime.now(timezone.utc)

        # 1. Read state data through storage module (Rule 2, 34)
        scored_listings = storage.get_scored_listings(db_path)
        scores = [int(l["fit_score"]) for l in scored_listings if l.get("fit_score") is not None]

        facts_list = storage.get_all_extractions(db_path)
        gap_snapshot = storage.get_latest_gap_snapshot(db_path)
        if isinstance(gap_snapshot, list):
            gaps = gap_snapshot
        elif isinstance(gap_snapshot, dict):
            gaps = gap_snapshot.get("gaps", [])
        else:
            gaps = []
        latest_fetch_at = storage.last_fetch_time(db_path)

        # 2. Run all checks deterministically
        verdict: Verdict = run_all_checks(
            scores=scores,
            facts_list=facts_list,
            gaps=gaps,
            latest_fetch_at=latest_fetch_at,
            config=config,
            now=now,
        )

        # 3. Format AgentResult
        if verdict.passed:
            status = "ok"
            notes = f"VERDICT: pass — {verdict.summary}"
        else:
            status = "failed"
            fail_msgs = [f"{c.name} ({c.message})" for c in verdict.failed_checks]
            notes = f"VERDICT: fail — {'; '.join(fail_msgs)}"

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=len(verdict.results),
            notes=notes,
        )
