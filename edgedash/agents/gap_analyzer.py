from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.skills import canonical


class GapAnalyzer:
    """Deterministic Gap Analyzer agent calculating opportunity cost and ranking skill gaps (Rule 22-27)."""

    @property
    def name(self) -> str:
        return "GapAnalyzer"

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        scored = storage.get_scored_listings(db_path)
        if not scored:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="0 scored listings to analyse",
            )

        # 1. Canonical user skills set
        aliases = config.skill_aliases or {}
        my_canonical = {canonical(s, aliases) for s in (config.my_skills or []) if s}

        # 2. Collect missing required skills and nice-to-haves
        gaps_map: dict[str, list[tuple[str, int]]] = {}
        nice_map: dict[str, int] = {}

        for listing in scored:
            score = listing.get("fit_score")
            if score is None:
                continue

            desc = (listing.get("description") or "").strip()
            desc_hash = hashlib.sha256(desc.encode("utf-8")).hexdigest()
            facts = storage.get_extraction(db_path, desc_hash)
            if not facts:
                continue

            # Required skills (primary gap metric)
            req_skills = facts.get("required_skills") or []
            seen_in_listing: set[str] = set()
            for r in req_skills:
                c = canonical(r, aliases)
                if c and (c not in my_canonical) and (c not in seen_in_listing):
                    gaps_map.setdefault(c, []).append((listing["id"], int(score)))
                    seen_in_listing.add(c)

            # Nice-to-have skills (tracked separately per requirement)
            nice_skills = facts.get("nice_to_have") or []
            seen_nice_in_listing: set[str] = set()
            for n in nice_skills:
                c = canonical(n, aliases)
                if c and (c not in my_canonical) and (c not in seen_nice_in_listing):
                    nice_map[c] = nice_map.get(c, 0) + 1
                    seen_nice_in_listing.add(c)

        # 3. Compute deterministic metrics for each missing skill (Rule 24, 26, 27)
        gap_records: list[dict[str, Any]] = []
        for skill, blocked_items in gaps_map.items():
            listings_blocked = len(blocked_items)
            # Rule 24: opportunity_cost = sum(score / 100)
            opp_cost = round(sum(s / 100.0 for _, s in blocked_items), 2)
            mean_score = round(sum(s for _, s in blocked_items) / listings_blocked, 1)
            top_score = max(s for _, s in blocked_items)

            # Rule 26: up to 5 highest-scoring listing IDs for drill-down traceability
            sorted_by_score = sorted(blocked_items, key=lambda x: x[1], reverse=True)
            example_ids = [lid for lid, _ in sorted_by_score[:5]]

            # Rule 27: confidence based on sample size
            confidence = "low" if listings_blocked < 3 else "high"

            gap_records.append({
                "skill": skill,
                "listings_blocked": listings_blocked,
                "opportunity_cost": opp_cost,
                "mean_score": mean_score,
                "top_score": top_score,
                "example_ids": example_ids,
                "also_nice_to_have": nice_map.get(skill, 0),
                "confidence": confidence,
            })

        # 4. Rank by opportunity_cost descending (Rule 24)
        gap_records.sort(key=lambda x: x["opportunity_cost"], reverse=True)
        top_10 = gap_records[:10]

        # 5. Write timestamped snapshot (Rule 25)
        now_dt = datetime.now(timezone.utc)
        run_id = f"run_{now_dt.strftime('%Y%m%d_%H%M%S')}"
        computed_at = now_dt.isoformat()
        storage.save_gap_snapshot(
            path=db_path,
            run_id=run_id,
            computed_at=computed_at,
            sample_size=len(scored),
            gaps=top_10,
        )

        # 6. Format AgentResult notes
        if top_10:
            top_gap = top_10[0]
            notes = (
                f"{len(top_10)} gaps · top: {top_gap['skill']} "
                f"({top_gap['listings_blocked']} listings, cost {top_gap['opportunity_cost']}) · "
                f"{len(scored)} listings analysed"
            )
        else:
            notes = f"0 gaps identified · {len(scored)} listings analysed"

        return AgentResult(
            agent=self.name,
            status="ok",
            records_touched=len(top_10),
            notes=notes,
        )
