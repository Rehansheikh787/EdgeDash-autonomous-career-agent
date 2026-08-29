from __future__ import annotations

from datetime import datetime, timezone
import edgedash.sources  # Ensure sources registry is loaded
from edgedash import storage
from edgedash.agents.base import AgentResult
from edgedash.config import Config
from edgedash.sources.base import SOURCES


class Fetcher:
    """Real fetcher coordinating external job sources."""

    @property
    def name(self) -> str:
        return "Fetcher"

    def run(
        self,
        config: Config,
        db_path: str,
        stop_conditions: dict[str, Any] | None = None,
    ) -> AgentResult:
        total_inserted = 0
        notes_parts: list[str] = []
        any_success = False

        for source_name in config.sources:
            source_cls = SOURCES.get(source_name)
            if not source_cls:
                err_msg = f"Unknown source '{source_name}'"
                print(f"  [Fetcher] WARNING: {err_msg}")
                notes_parts.append(f"{source_name}: FAILED ({err_msg})")
                continue

            started_at = datetime.now(timezone.utc).isoformat()
            try:
                source_inst = source_cls()
                rows = source_inst.fetch(config)
                finished_at = datetime.now(timezone.utc).isoformat()

                now_str = datetime.now(timezone.utc).isoformat()
                listing_inputs: list[storage.ListingInput] = []
                for row in rows:
                    listing_inputs.append({
                        "title": row.get("title") or "Untitled",
                        "company": row.get("company") or "Unknown Company",
                        "location": row.get("location") or config.target_city or "Unknown",
                        "url": row.get("url") or "",
                        "description": row.get("description") or "",
                        "source": row.get("source") or source_name,
                        "posted_at": row.get("posted_at") or now_str,
                        "fetched_at": now_str,
                    })

                inserted = storage.upsert_listings(db_path, listing_inputs)
                total_inserted += inserted
                any_success = True

                storage.log_cycle(
                    db_path,
                    agent=source_name,
                    started_at=started_at,
                    finished_at=finished_at,
                    records_touched=inserted,
                    status="ok",
                    notes=f"{len(rows)} fetched, {inserted} new",
                )
                notes_parts.append(f"{source_name}: {len(rows)} rows ({inserted} new)")

            except Exception as exc:
                finished_at = datetime.now(timezone.utc).isoformat()
                print(f"  [Fetcher] WARNING: Source '{source_name}' failed: {exc}")
                storage.log_cycle(
                    db_path,
                    agent=source_name,
                    started_at=started_at,
                    finished_at=finished_at,
                    records_touched=0,
                    status="failed",
                    notes=str(exc),
                )
                notes_parts.append(f"{source_name}: FAILED ({exc})")

        notes = " | ".join(notes_parts) if notes_parts else "No sources configured"
        status = "ok" if any_success or not config.sources else "failed"

        return AgentResult(
            agent=self.name,
            status=status,
            records_touched=total_inserted,
            notes=notes,
        )
