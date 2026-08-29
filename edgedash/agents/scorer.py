from __future__ import annotations

from typing import Any

from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.agents.extractor import extract
from edgedash.config import Config
from edgedash.scoring import score_listing


class Scorer:
    """Scorer agent extracting facts and deterministically scoring listings."""

    @property
    def name(self) -> str:
        return "Scorer"

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        widen = bool((stop_conditions or {}).get("widen_distribution", False))
        limit = (stop_conditions or {}).get("max_items") or getattr(config, "score_batch_size", 25)

        if widen:
            # Re-scoring existing scored listings to expand spread
            target_listings = storage.get_scored_listings(db_path)[:limit]
            if not target_listings:
                target_listings = storage.get_unscored_listings(db_path, limit)
        else:
            target_listings = storage.get_unscored_listings(db_path, limit)

        if not target_listings:
            return AgentResult(
                agent=self.name,
                status="ok",
                records_touched=0,
                notes="0 listings to process",
            )

        scores: list[int] = []
        failed_count = 0

        for listing in target_listings:
            try:
                facts = extract(listing, db_path, config=config)
                score_res = score_listing(listing, facts, config, widen_distribution=widen)
                storage.update_listing_score(
                    db_path,
                    listing_id=listing["id"],
                    fit_score=score_res["score"],
                    fit_reason=score_res["reason"],
                )
                scores.append(score_res["score"])
            except Exception as exc:
                failed_count += 1
                print(f"  [Scorer] WARNING: Failed scoring listing '{listing.get('id')}': {exc}")

        if scores:
            min_score = min(scores)
            max_score = max(scores)
            mean_score = round(sum(scores) / len(scores), 1)
            spread = max_score - min_score
            spread_status = "SUSPECT" if (spread < 10 and len(scores) >= 5) else "OK"

            notes = (
                f"scored {len(scores)} · range {min_score}-{max_score} · "
                f"mean {mean_score} · {failed_count} failed · spread {spread_status}"
            )
            status = "ok"
        else:
            notes = f"0 scored · {failed_count} failed"
            status = "failed" if failed_count > 0 else "ok"

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=len(scores),
            notes=notes,
        )
