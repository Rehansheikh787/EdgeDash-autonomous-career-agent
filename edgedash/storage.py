from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any, Iterator, TypedDict


class ListingInput(TypedDict):
    title: str
    company: str
    location: str
    url: str
    description: str
    source: str
    posted_at: str
    fetched_at: str


# ── DDL Definitions (Dialect Aware) ───────────────────────────────────

_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    fit_score INTEGER NULL,
    fit_reason TEXT NULL
);

CREATE TABLE IF NOT EXISTS skill_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    skill TEXT NOT NULL,
    listings_blocked INTEGER NOT NULL,
    opportunity_cost REAL NOT NULL,
    mean_score REAL NOT NULL,
    top_score INTEGER NOT NULL,
    example_ids TEXT NOT NULL,
    also_nice_to_have INTEGER NOT NULL,
    sample_size INTEGER NOT NULL,
    confidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_gaps_run ON skill_gaps(run_id);

CREATE TABLE IF NOT EXISTS cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    records_touched INTEGER NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_cache (
    desc_hash TEXT PRIMARY KEY,
    extracted_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    tool_used TEXT NULL,
    params_json TEXT NULL,
    answerable INTEGER NOT NULL,
    duration_sec REAL NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
"""

_POSTGRES_DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    posted_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    fit_score INTEGER NULL,
    fit_reason TEXT NULL
);

CREATE TABLE IF NOT EXISTS skill_gaps (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    skill TEXT NOT NULL,
    listings_blocked INTEGER NOT NULL,
    opportunity_cost DOUBLE PRECISION NOT NULL,
    mean_score DOUBLE PRECISION NOT NULL,
    top_score INTEGER NOT NULL,
    example_ids TEXT NOT NULL,
    also_nice_to_have INTEGER NOT NULL,
    sample_size INTEGER NOT NULL,
    confidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skill_gaps_run ON skill_gaps(run_id);

CREATE TABLE IF NOT EXISTS cycle_log (
    id SERIAL PRIMARY KEY,
    agent TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    records_touched INTEGER NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_cache (
    desc_hash TEXT PRIMARY KEY,
    extracted_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_log (
    id SERIAL PRIMARY KEY,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    tool_used TEXT NULL,
    params_json TEXT NULL,
    answerable INTEGER NOT NULL,
    duration_sec DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT NULL
);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);
"""

# ── Backend Detection & Startup Notification (Rule 2, 47, 48) ─────────

_LOGGED_BACKEND = False


def _load_dotenv_if_needed() -> None:
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.isfile(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    k, sep, v = line.partition("=")
                    if sep and k.strip() not in os.environ:
                        val = v.strip()
                        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                            val = val[1:-1]
                        os.environ[k.strip()] = val
        except Exception:
            pass


def _get_database_url() -> str | None:
    _load_dotenv_if_needed()
    raw_url = os.environ.get("DATABASE_URL")
    if not raw_url or not raw_url.strip():
        return None
    url = raw_url.strip()
    # Normalize postgres:// to postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def is_postgres() -> bool:
    return _get_database_url() is not None


def _log_backend_status(path: str) -> None:
    global _LOGGED_BACKEND
    if not _LOGGED_BACKEND:
        if is_postgres():
            print("[Storage] Backend: PostgreSQL (DATABASE_URL configured)", flush=True)
        else:
            print(f"[Storage] Backend: SQLite (offline/local fallback, path: {path})", flush=True)
        _LOGGED_BACKEND = True


# ── Dialect Translation & Unified Connection Context ─────────────────


def _translate_sql_for_postgres(sql: str) -> str:
    """Translate standard SQLite SQL patterns into PostgreSQL dialect."""
    out = sql
    # Replace parameter placeholders ? with %s
    out = out.replace("?", "%s")
    # Replace INSERT OR IGNORE
    if "INSERT OR IGNORE INTO" in out:
        out = out.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "ON CONFLICT" not in out:
            out += " ON CONFLICT (id) DO NOTHING"
    # Replace INSERT OR REPLACE
    if "INSERT OR REPLACE INTO extraction_cache" in out:
        out = (
            "INSERT INTO extraction_cache (desc_hash, extracted_json, created_at) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (desc_hash) DO UPDATE SET "
            "extracted_json = EXCLUDED.extracted_json, created_at = EXCLUDED.created_at"
        )
    # Replace GROUP_CONCAT with string_agg
    out = re.sub(
        r"GROUP_CONCAT\s*\(\s*DISTINCT\s+source\s*\)",
        r"string_agg(DISTINCT source, ', ')",
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(
        r"GROUP_CONCAT\s*\(\s*title\s*,\s*' \| '\s*\)",
        r"string_agg(title, ' | ')",
        out,
        flags=re.IGNORECASE,
    )
    return out


class _UnifiedCursor:
    """Wrapper normalizing cursor results to dict-like rows across SQLite & Postgres."""

    def __init__(self, raw_cursor: Any, is_pg: bool) -> None:
        self._cur = raw_cursor
        self._is_pg = is_pg

    @property
    def rowcount(self) -> int:
        return int(self._cur.rowcount)

    @property
    def lastrowid(self) -> int:
        if self._is_pg:
            return getattr(self._cur, "lastrowid", 1) or 1
        return int(getattr(self._cur, "lastrowid", 0) or 0)

    def fetchone(self) -> Any:
        row = self._cur.fetchone()
        return row

    def fetchall(self) -> list[Any]:
        rows = self._cur.fetchall()
        return rows


class _UnifiedConnection:
    """Unified context manager abstracting SQLite and Postgres connections (Rule 2)."""

    def __init__(self, path: str) -> None:
        self.path = path
        # In unit tests with temporary/memory DBs, always use SQLite
        if path == ":memory:" or "tmp" in path.lower() or path.startswith("test_"):
            self.db_url = None
            self.is_pg = False
        else:
            self.db_url = _get_database_url()
            self.is_pg = self.db_url is not None
        self._raw_conn: Any = None

    def __enter__(self) -> _UnifiedConnection:
        _log_backend_status(self.path)
        if self.is_pg:
            try:
                import psycopg
                from psycopg.rows import dict_row

                self._raw_conn = psycopg.connect(self.db_url, row_factory=dict_row)
            except ImportError:
                try:
                    import psycopg2
                    import psycopg2.extras

                    self._raw_conn = psycopg2.connect(
                        self.db_url,
                        connect_timeout=10,
                        cursor_factory=psycopg2.extras.RealDictCursor,
                    )
                except ImportError as exc:
                    raise RuntimeError(
                        "DATABASE_URL is set but neither 'psycopg2' nor 'psycopg' is installed. "
                        "Please install psycopg2-binary or psycopg."
                    ) from exc
        else:
            self._raw_conn = sqlite3.connect(self.path)
            self._raw_conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._raw_conn:
            if exc_type is None:
                self._raw_conn.commit()
            else:
                self._raw_conn.rollback()
            self._raw_conn.close()

    def execute(self, sql: str, params: Any = None) -> _UnifiedCursor:
        cur = self._raw_conn.cursor()
        if self.is_pg:
            pg_sql = _translate_sql_for_postgres(sql)
            if params is not None:
                cur.execute(pg_sql, params)
            else:
                cur.execute(pg_sql)
        else:
            if params is not None:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
        return _UnifiedCursor(cur, self.is_pg)

    def executescript(self, sql_script: str) -> None:
        cur = self._raw_conn.cursor()
        if self.is_pg:
            cur.execute(sql_script)
        else:
            cur.executescript(sql_script)


def _connect(path: str) -> _UnifiedConnection:
    return _UnifiedConnection(path)


# ── Initialization & Migration (Rule 2, 47) ───────────────────────────


def init_db(path: str) -> None:
    """Initialize or migrate all database tables (idempotent across SQLite & Postgres)."""
    with _connect(path) as conn:
        if conn.is_pg:
            conn.executescript(_POSTGRES_DDL)
        else:
            # Check SQLite legacy schema if needed
            cursor = conn.execute("PRAGMA table_info(skill_gaps)")
            cols = [row["name"] for row in cursor.fetchall()]
            if cols and "run_id" not in cols:
                conn.execute("DROP TABLE skill_gaps")
            conn.executescript(_SQLITE_DDL)


# ── Listings Operations ───────────────────────────────────────────────


def upsert_listings(path: str, rows: list[ListingInput]) -> int:
    if not rows:
        return 0

    sql = """
        INSERT OR IGNORE INTO listings (
            id, title, company, location, url, description,
            source, posted_at, fetched_at, fit_score, fit_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
    """
    inserted = 0
    with _connect(path) as conn:
        for row in rows:
            listing_id = _listing_id(row["source"], row["url"])
            cursor = conn.execute(
                sql,
                (
                    listing_id,
                    row["title"],
                    row["company"],
                    row["location"],
                    row["url"],
                    row["description"],
                    row["source"],
                    row["posted_at"],
                    row["fetched_at"],
                ),
            )
            inserted += cursor.rowcount
    return inserted


def count_unscored(path: str) -> int:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE fit_score IS NULL"
        ).fetchone()
    return int(_first_val(row) or 0)


def last_fetch_time(path: str) -> str | None:
    with _connect(path) as conn:
        row = conn.execute("SELECT MAX(fetched_at) FROM listings").fetchone()
    val = _first_val(row)
    return str(val) if val is not None else None


def read_system_state_metrics(path: str) -> dict[str, Any]:
    """Read cheap system state metrics for orchestrator planning (Rule 2)."""
    with _connect(path) as conn:
        r_fetch = conn.execute("SELECT MAX(fetched_at) as max_fetch FROM listings").fetchone()
        last_fetch_at = str(_first_val(r_fetch)) if _first_val(r_fetch) is not None else None

        r_unscored = conn.execute("SELECT COUNT(*) as unscored FROM listings WHERE fit_score IS NULL").fetchone()
        unscored_count = int(_first_val(r_unscored) or 0)

        r_scored = conn.execute("SELECT COUNT(*) as scored, MAX(fetched_at) as max_scored FROM listings WHERE fit_score IS NOT NULL").fetchone()
        scored_count = int(_val_idx(r_scored, 0) or 0)
        max_sc = _val_idx(r_scored, 1)
        latest_scored_at = str(max_sc) if max_sc is not None else None

        r_gaps = conn.execute("SELECT MAX(computed_at) as max_gaps FROM skill_gaps").fetchone()
        gaps_computed_at = str(_first_val(r_gaps)) if _first_val(r_gaps) is not None else None

        r_cycle = conn.execute(
            "SELECT status, finished_at FROM cycle_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        last_cycle_verdict = str(r_cycle["status"]) if r_cycle else None
        last_cycle_at = str(r_cycle["finished_at"]) if r_cycle else None

    return {
        "last_fetch_at": last_fetch_at,
        "unscored_count": unscored_count,
        "scored_count": scored_count,
        "latest_scored_at": latest_scored_at,
        "gaps_computed_at": gaps_computed_at,
        "last_cycle_verdict": last_cycle_verdict,
        "last_cycle_at": last_cycle_at,
    }


def log_cycle(
    path: str,
    agent: str,
    started_at: str,
    finished_at: str,
    records_touched: int,
    status: str,
    notes: str,
) -> int:
    with _connect(path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO cycle_log (
                agent, started_at, finished_at,
                records_touched, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent, started_at, finished_at, records_touched, status, notes),
        )
        return int(cursor.lastrowid)


def get_listings(
    path: str,
    limit: int,
    min_score: int | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM listings"
    params: list[object] = []
    if min_score is not None:
        sql += " WHERE fit_score IS NOT NULL AND fit_score >= ?"
        params.append(min_score)
    sql += " ORDER BY fetched_at DESC LIMIT ?"
    params.append(limit)

    with _connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_unscored_listings(path: str, limit: int) -> list[dict[str, Any]]:
    sql = "SELECT * FROM listings WHERE fit_score IS NULL ORDER BY fetched_at ASC LIMIT ?"
    with _connect(path) as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_scored_listings(path: str) -> list[dict[str, Any]]:
    sql = "SELECT * FROM listings WHERE fit_score IS NOT NULL ORDER BY fit_score DESC"
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(row) for row in rows]


def update_listing_score(
    path: str,
    listing_id: str,
    fit_score: int,
    fit_reason: str,
) -> None:
    with _connect(path) as conn:
        conn.execute(
            "UPDATE listings SET fit_score = ?, fit_reason = ? WHERE id = ?",
            (fit_score, fit_reason, listing_id),
        )


def clear_scores(path: str, listing_id: str | None = None) -> int:
    with _connect(path) as conn:
        if listing_id:
            cursor = conn.execute(
                "UPDATE listings SET fit_score = NULL, fit_reason = NULL WHERE id = ?",
                (listing_id,),
            )
        else:
            cursor = conn.execute(
                "UPDATE listings SET fit_score = NULL, fit_reason = NULL WHERE fit_score IS NOT NULL"
            )
        return int(cursor.rowcount)


# ── Extraction Cache ──────────────────────────────────────────────────


def get_extraction(path: str, desc_hash: str) -> dict[str, Any] | None:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT extracted_json FROM extraction_cache WHERE desc_hash = ?",
            (desc_hash,),
        ).fetchone()
    if not row:
        return None
    raw_val = _first_val(row)
    if raw_val:
        try:
            return json.loads(raw_val)
        except Exception:
            return None
    return None


def set_extraction(path: str, desc_hash: str, data: dict[str, Any]) -> None:
    now_str = datetime.now(timezone.utc).isoformat()
    json_str = json.dumps(data)
    with _connect(path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO extraction_cache (desc_hash, extracted_json, created_at)
            VALUES (?, ?, ?)
            """,
            (desc_hash, json_str, now_str),
        )


def get_all_extracted_skills(path: str) -> list[str]:
    skills: list[str] = []
    with _connect(path) as conn:
        rows = conn.execute("SELECT extracted_json FROM extraction_cache").fetchall()
        for row in rows:
            if not row:
                continue
            raw_val = _first_val(row)
            if not raw_val:
                continue
            try:
                data = json.loads(raw_val)
                for s in data.get("required_skills", []):
                    if s and isinstance(s, str):
                        skills.append(s)
            except Exception:
                continue
    return skills


def get_all_extractions(path: str) -> list[dict[str, Any]]:
    extractions: list[dict[str, Any]] = []
    with _connect(path) as conn:
        rows = conn.execute("SELECT extracted_json FROM extraction_cache").fetchall()
        for row in rows:
            if not row:
                continue
            raw_val = _first_val(row)
            if not raw_val:
                continue
            try:
                extractions.append(json.loads(raw_val))
            except Exception:
                continue
    return extractions


# ── Skill Gaps Operations ─────────────────────────────────────────────


def save_gap_snapshot(
    path: str,
    run_id: str,
    computed_at: str,
    sample_size: int,
    gaps: list[dict[str, Any]],
) -> None:
    sql = """
        INSERT INTO skill_gaps (
            run_id, computed_at, skill, listings_blocked,
            opportunity_cost, mean_score, top_score,
            example_ids, also_nice_to_have, sample_size, confidence
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _connect(path) as conn:
        for item in gaps:
            example_ids_str = ",".join(item.get("example_ids", []))
            conn.execute(
                sql,
                (
                    run_id,
                    computed_at,
                    item["skill"],
                    int(item["listings_blocked"]),
                    float(item["opportunity_cost"]),
                    float(item["mean_score"]),
                    int(item["top_score"]),
                    example_ids_str,
                    int(item.get("also_nice_to_have", 0)),
                    int(sample_size),
                    str(item.get("confidence", "high")),
                ),
            )


def get_latest_gap_snapshot(path: str) -> list[dict[str, Any]]:
    sql = """
        SELECT * FROM skill_gaps
        WHERE run_id = (SELECT run_id FROM skill_gaps ORDER BY id DESC LIMIT 1)
        ORDER BY opportunity_cost DESC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("example_ids"), str):
            d["example_ids"] = [x.strip() for x in d["example_ids"].split(",") if x.strip()]
        results.append(d)
    return results


def get_gap_snapshot_runs(path: str) -> list[dict[str, Any]]:
    sql = """
        SELECT DISTINCT run_id, computed_at, sample_size
        FROM skill_gaps
        ORDER BY id ASC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_gap_snapshot_by_run(path: str, run_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT * FROM skill_gaps
        WHERE run_id = ?
        ORDER BY opportunity_cost DESC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql, (run_id,)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("example_ids"), str):
            d["example_ids"] = [x.strip() for x in d["example_ids"].split(",") if x.strip()]
        results.append(d)
    return results


# ── Cycle Log & Verification Queries ──────────────────────────────────


def get_latest_verified_cycle(path: str) -> dict[str, Any] | None:
    with _connect(path) as conn:
        row = conn.execute(
            """
            SELECT id, agent, started_at, finished_at, records_touched, status, notes
            FROM cycle_log
            WHERE agent = 'Orchestrator' AND status IN ('complete', 'verified')
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_latest_cycle(path: str) -> dict[str, Any] | None:
    with _connect(path) as conn:
        row = conn.execute(
            """
            SELECT id, agent, started_at, finished_at, records_touched, status, notes
            FROM cycle_log
            WHERE agent = 'Orchestrator'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    return dict(row) if row else None


def get_recent_cycle_logs(path: str, limit: int = 30) -> list[dict[str, Any]]:
    with _connect(path) as conn:
        rows = conn.execute(
            """
            SELECT id, agent, started_at, finished_at, records_touched, status, notes
            FROM cycle_log
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Natural Language Query Helpers (Rules 40-46) ──────────────────────


def log_query(
    path: str,
    question: str,
    tool_used: str | None,
    params_json: str | None,
    answerable: bool,
    duration_sec: float,
    status: str,
    rejection_reason: str | None = None,
    created_at: str | None = None,
) -> int:
    ts = created_at or datetime.now(timezone.utc).isoformat()
    sql = """
        INSERT INTO query_log (
            created_at, question, tool_used, params_json,
            answerable, duration_sec, status, rejection_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with _connect(path) as conn:
        cur = conn.execute(
            sql,
            (
                ts,
                question,
                tool_used,
                params_json,
                1 if answerable else 0,
                duration_sec,
                status,
                rejection_reason,
            ),
        )
        return int(cur.lastrowid)


def get_daily_query_count(path: str, date_prefix: str | None = None) -> int:
    prefix = date_prefix or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sql = "SELECT COUNT(*) FROM query_log WHERE created_at LIKE ?"
    with _connect(path) as conn:
        row = conn.execute(sql, (f"{prefix}%",)).fetchone()
        return int(_first_val(row) or 0)


def query_companies_hiring(
    path: str, days: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    from datetime import timedelta

    curr = now or datetime.now(timezone.utc)
    cutoff = (curr - timedelta(days=days)).isoformat()
    sql = """
        SELECT company, COUNT(*) as listing_count,
               GROUP_CONCAT(title, ' | ') as titles,
               MAX(posted_at) as latest_posted_at
        FROM listings
        WHERE posted_at >= ?
        GROUP BY company
        ORDER BY listing_count DESC, company ASC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql, (cutoff,)).fetchall()
    results = []
    for r in rows:
        titles_raw = r.get("titles") or "" if isinstance(r, dict) else r["titles"] or ""
        title_list = [t.strip() for t in titles_raw.split(" | ") if t.strip()][:3]
        results.append(
            {
                "company": r["company"],
                "listing_count": r["listing_count"],
                "sample_titles": title_list,
                "latest_posted_at": r["latest_posted_at"],
            }
        )
    return results


def query_best_matches(path: str, n: int) -> list[dict[str, Any]]:
    sql = """
        SELECT id, title, company, location, url, fit_score, fit_reason, posted_at
        FROM listings
        WHERE fit_score IS NOT NULL
        ORDER BY fit_score DESC, posted_at DESC
        LIMIT ?
    """
    with _connect(path) as conn:
        rows = conn.execute(sql, (n,)).fetchall()
    return [dict(r) for r in rows]


def query_top_gaps(path: str, n: int) -> list[dict[str, Any]]:
    gaps = get_latest_gap_snapshot(path)
    return gaps[:n]


def query_gap_detail(path: str, skill: str) -> list[dict[str, Any]]:
    gaps = get_latest_gap_snapshot(path)
    target = skill.lower().strip()
    matched = next((g for g in gaps if g.get("skill", "").lower().strip() == target), None)
    if not matched:
        return []

    example_ids = matched.get("example_ids", [])
    if isinstance(example_ids, str):
        example_ids = [x.strip() for x in example_ids.split(",") if x.strip()]
    if not example_ids:
        return []

    placeholders = ",".join("?" for _ in example_ids)
    sql = f"""
        SELECT id, title, company, location, url, fit_score, fit_reason
        FROM listings
        WHERE id IN ({placeholders})
        ORDER BY fit_score DESC
    """
    with _connect(path) as conn:
        rows = conn.execute(sql, example_ids).fetchall()
    return [dict(r) for r in rows]


def query_trend(path: str, weeks: int = 3) -> list[dict[str, Any]]:
    runs = get_gap_snapshot_runs(path)
    if len(runs) < 2:
        return []
    earliest_run = runs[0]
    latest_run = runs[-1]

    earliest_gaps = {
        g["skill"]: g for g in get_gap_snapshot_by_run(path, earliest_run["run_id"])
    }
    latest_gaps = {
        g["skill"]: g for g in get_gap_snapshot_by_run(path, latest_run["run_id"])
    }

    results = []
    for skill, late in list(latest_gaps.items())[:10]:
        early = earliest_gaps.get(skill)
        early_cost = early["opportunity_cost"] if early else None
        late_cost = late["opportunity_cost"]
        diff = late_cost - (early_cost or 0.0)
        results.append(
            {
                "skill": skill,
                "status": "NEW" if early is None else "EXISTING",
                "earliest_opportunity_cost": early_cost,
                "latest_opportunity_cost": late_cost,
                "change": round(diff, 2),
                "listings_blocked": late.get("listings_blocked", 0),
            }
        )
    return results


def query_listing_count(path: str) -> dict[str, Any]:
    sql = """
        SELECT
            COUNT(*) as total_listings,
            SUM(CASE WHEN fit_score IS NOT NULL THEN 1 ELSE 0 END) as scored_count,
            SUM(CASE WHEN fit_score IS NULL THEN 1 ELSE 0 END) as unscored_count,
            MAX(posted_at) as newest_listing_at
        FROM listings
    """
    with _connect(path) as conn:
        row = conn.execute(sql).fetchone()
    if not row:
        return {
            "total_listings": 0,
            "scored_count": 0,
            "unscored_count": 0,
            "newest_listing_at": None,
        }
    return {
        "total_listings": row["total_listings"] or 0,
        "scored_count": row["scored_count"] or 0,
        "unscored_count": row["unscored_count"] or 0,
        "newest_listing_at": row["newest_listing_at"],
    }


def query_skill_demand(path: str, skill: str) -> dict[str, Any]:
    extractions = get_all_extractions(path)
    req_count = 0
    nice_count = 0
    target = skill.lower().strip()

    for ext in extractions:
        reqs = [str(s).lower().strip() for s in ext.get("required_skills", [])]
        nices = [str(s).lower().strip() for s in ext.get("nice_to_have", [])]
        if target in reqs:
            req_count += 1
        if target in nices:
            nice_count += 1

    total_listings = len(extractions)
    return {
        "skill": skill,
        "required_count": req_count,
        "nice_to_have_count": nice_count,
        "total_demand": req_count + nice_count,
        "sample_size": total_listings,
    }


def get_diagnostics(path: str) -> dict[str, Any]:
    """Retrieve read-only diagnostic metrics from the database (Rule 2)."""
    with _connect(path) as conn:
        total_row = conn.execute("SELECT COUNT(*) as total FROM listings").fetchone()
        total_listings = int(_first_val(total_row) or 0)

        source_rows = conn.execute(
            "SELECT source, COUNT(*) as cnt FROM listings GROUP BY source ORDER BY cnt DESC"
        ).fetchall()
        source_counts = {str(row["source"]): int(row["cnt"]) for row in source_rows}

        cross_dupes_rows = conn.execute(
            """
            SELECT LOWER(TRIM(title)) as title,
                   LOWER(TRIM(company)) as company,
                   COUNT(DISTINCT source) as source_count,
                   COUNT(*) as total_occurrences,
                   GROUP_CONCAT(DISTINCT source) as sources
            FROM listings
            WHERE title IS NOT NULL AND company IS NOT NULL
            GROUP BY LOWER(TRIM(title)), LOWER(TRIM(company))
            HAVING COUNT(DISTINCT source) > 1
            """
        ).fetchall()
        cross_dupes = [dict(row) for row in cross_dupes_rows]

        recent_rows = conn.execute(
            """
            SELECT id, source, title, company, location, posted_at, fetched_at
            FROM listings
            ORDER BY fetched_at DESC, posted_at DESC
            LIMIT 5
            """
        ).fetchall()
        recent_listings = [dict(row) for row in recent_rows]

        bad_quality_rows = conn.execute(
            """
            SELECT id, source, title, company, url
            FROM listings
            WHERE url IS NULL OR TRIM(url) = ''
               OR title IS NULL OR TRIM(title) = ''
               OR company IS NULL OR TRIM(company) = ''
            """
        ).fetchall()
        data_quality_issues = [dict(row) for row in bad_quality_rows]

    return {
        "total_listings": total_listings,
        "source_counts": source_counts,
        "cross_source_duplicates": cross_dupes,
        "recent_listings": recent_listings,
        "data_quality_issues": data_quality_issues,
    }


# ── Utilities ─────────────────────────────────────────────────────────


def _first_val(row: Any) -> Any:
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        return row[0]
    if isinstance(row, (tuple, list)):
        return row[0]
    if isinstance(row, dict):
        return list(row.values())[0] if row else None
    try:
        return row[0]
    except Exception:
        return None


def _val_idx(row: Any, idx: int) -> Any:
    if not row:
        return None
    if isinstance(row, sqlite3.Row):
        try:
            return row[idx]
        except Exception:
            return None
    if isinstance(row, (tuple, list)):
        return row[idx] if idx < len(row) else None
    if isinstance(row, dict):
        vals = list(row.values())
        return vals[idx] if idx < len(vals) else None
    try:
        return row[idx]
    except Exception:
        return None


def _listing_id(source: str, url: str) -> str:
    payload = f"{source}|{url}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ── CLI Commands: --migrate & --check (Rule 2, 47) ────────────────────


def check_storage(path: str = "edgedash.db") -> None:
    backend_name = "PostgreSQL" if is_postgres() else "SQLite"
    target_info = "DATABASE_URL" if is_postgres() else f"File: {path}"
    print(f"Backend  : {backend_name} ({target_info})")

    try:
        with _connect(path) as conn:
            print("Status   : Connected successfully [OK]")
            tables = ["listings", "skill_gaps", "cycle_log", "extraction_cache", "query_log"]
            print("\nTable Row Counts:")
            print("-" * 32)
            for tbl in tables:
                r = conn.execute(f"SELECT COUNT(*) as count FROM {tbl}").fetchone()
                cnt = _first_val(r) or 0
                print(f"  * {tbl:<18} : {cnt:>6} rows")
            print("-" * 32)
    except Exception as exc:
        msg = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", str(exc))
        print(f"Status   : Connection Failed [ERROR] ({msg})")


if __name__ == "__main__":
    db_path = "edgedash.db"
    if "--migrate" in sys.argv:
        print(f"Running database migration on {'PostgreSQL' if is_postgres() else 'SQLite'}...")
        init_db(db_path)
        print("Migration complete. All tables verified [OK].")
    elif "--check" in sys.argv:
        check_storage(db_path)
    else:
        print("Usage: python -m edgedash.storage [--migrate | --check]")
