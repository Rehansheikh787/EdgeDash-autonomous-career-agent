from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from edgedash import storage
from edgedash.config import Config, load_config
from edgedash.skills import canonical


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., dict[str, Any]]


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, description: str, parameters: dict[str, Any]):
    """Decorator to register a parameterised read-only query tool (Rule 40, 41)."""
    def decorator(fn: Callable[..., dict[str, Any]]):
        TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            parameters=parameters,
            func=fn,
        )
        return fn
    return decorator


# ── Parameter Validation & Clamping Helpers (Rule 41) ─────────────────


def _clamp_int(value: Any, default: int, min_val: int, max_val: int) -> int:
    """Validate and clamp untrusted model input into a safe range (Rule 41)."""
    try:
        val = int(value)
        return max(min_val, min(max_val, val))
    except (ValueError, TypeError):
        return default


def _clean_skill_param(skill: Any, config: Config) -> str:
    """Canonicalize and sanitize a skill parameter string."""
    if not skill or not isinstance(skill, str):
        return ""
    cleaned = skill.strip().lower()
    return canonical(cleaned, config.skill_aliases)


# ── Tool 1: companies_hiring ──────────────────────────────────────────


@tool(
    name="companies_hiring",
    description=(
        "Returns companies actively hiring with listings posted within the last N days, "
        "including job count and recent job titles. Use when the user asks which companies "
        "are hiring, who has open roles, or what employers are in the market."
    ),
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "Lookback window in days (clamped 1-90, default 7)",
                "default": 7,
                "minimum": 1,
                "maximum": 90,
            }
        },
    },
)
def companies_hiring(
    db_path: str,
    days: int = 7,
    config: Config | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    safe_days = _clamp_int(days, default=7, min_val=1, max_val=90)
    current_time = now or datetime.now(timezone.utc)
    rows = storage.query_companies_hiring(db_path, days=safe_days, now=current_time)

    total_listings = sum(r.get("listing_count", 0) for r in rows)
    company_count = len(rows)

    summary = (
        f"Found {company_count} company(ies) with {total_listings} listing(s) "
        f"posted in the last {safe_days} day(s)."
    )
    return {
        "tool": "companies_hiring",
        "summary": summary,
        "rows": rows,
    }


# ── Tool 2: best_matches ──────────────────────────────────────────────


@tool(
    name="best_matches",
    description=(
        "Returns top N highest-scoring job listings matching your profile with fit score, "
        "title, company, location, and reason. Use when the user asks for top jobs, best matches, "
        "highest scoring roles, or recommendations."
    ),
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of listings to return (clamped 1-25, default 10)",
                "default": 10,
                "minimum": 1,
                "maximum": 25,
            }
        },
    },
)
def best_matches(
    db_path: str,
    n: int = 10,
    config: Config | None = None,
) -> dict[str, Any]:
    safe_n = _clamp_int(n, default=10, min_val=1, max_val=25)
    rows = storage.query_best_matches(db_path, n=safe_n)

    summary = f"Retrieved top {len(rows)} highest-scoring verified job matches."
    return {
        "tool": "best_matches",
        "summary": summary,
        "rows": rows,
    }


# ── Tool 3: top_gaps ──────────────────────────────────────────────────


@tool(
    name="top_gaps",
    description=(
        "Returns top N missing skills ranked by market opportunity cost and number of listings blocked. "
        "Use when the user asks what skills to learn, top skill gaps, biggest weaknesses, or what is holding them back."
    ),
    parameters={
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of skill gaps to return (clamped 1-25, default 5)",
                "default": 5,
                "minimum": 1,
                "maximum": 25,
            }
        },
    },
)
def top_gaps(
    db_path: str,
    n: int = 5,
    config: Config | None = None,
) -> dict[str, Any]:
    safe_n = _clamp_int(n, default=5, min_val=1, max_val=25)
    rows = storage.query_top_gaps(db_path, n=safe_n)

    summary = f"Found {len(rows)} top skill gap(s) ranked by opportunity cost from verified snapshot."
    return {
        "tool": "top_gaps",
        "summary": summary,
        "rows": rows,
    }


# ── Tool 4: gap_detail ────────────────────────────────────────────────


@tool(
    name="gap_detail",
    description=(
        "Returns specific job listings blocked by one named skill, including company and score. "
        "Use when the user asks about a specific skill gap (e.g. 'Why do I need Kubernetes?', 'Show me jobs requiring Docker')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "The exact skill name to inspect (e.g. 'docker', 'kubernetes', 'python')",
            }
        },
        "required": ["skill"],
    },
)
def gap_detail(
    db_path: str,
    skill: str,
    config: Config | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    canonical_skill = _clean_skill_param(skill, cfg)
    if not canonical_skill:
        return {
            "tool": "gap_detail",
            "summary": "No valid skill specified.",
            "rows": [],
        }

    rows = storage.query_gap_detail(db_path, skill=canonical_skill)
    summary = (
        f"Found {len(rows)} listing(s) blocked by missing skill '{canonical_skill}'."
    )
    return {
        "tool": "gap_detail",
        "summary": summary,
        "rows": rows,
    }


# ── Tool 5: trend ─────────────────────────────────────────────────────


@tool(
    name="trend",
    description=(
        "Returns change in skill gap opportunity cost over N weeks from historical snapshots. "
        "Use when the user asks about skill trends, market shifts, what skills are rising or falling, or changes over time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "weeks": {
                "type": "integer",
                "description": "Trend window in weeks (clamped 1-12, default 3)",
                "default": 3,
                "minimum": 1,
                "maximum": 12,
            }
        },
    },
)
def trend(
    db_path: str,
    weeks: int = 3,
    config: Config | None = None,
) -> dict[str, Any]:
    safe_weeks = _clamp_int(weeks, default=3, min_val=1, max_val=12)
    rows = storage.query_trend(db_path, weeks=safe_weeks)

    if not rows:
        summary = "Only one snapshot exists so far. Multiple snapshot runs are required to compute trends."
    else:
        summary = f"Computed gap trends for {len(rows)} skill(s) across snapshot runs."

    return {
        "tool": "trend",
        "summary": summary,
        "rows": rows,
    }


# ── Tool 6: listing_count ─────────────────────────────────────────────


@tool(
    name="listing_count",
    description=(
        "Returns total number of job listings in the database, number scored vs unscored, and latest listing date. "
        "Use when the user asks how many jobs we have, database size, total listings count, or data summary."
    ),
    parameters={"type": "object", "properties": {}},
)
def listing_count(
    db_path: str,
    config: Config | None = None,
) -> dict[str, Any]:
    stats = storage.query_listing_count(db_path)
    total = stats.get("total_listings", 0)
    scored = stats.get("scored_count", 0)
    unscored = stats.get("unscored_count", 0)
    newest = stats.get("newest_listing_at") or "None"

    summary = (
        f"Database contains {total} total listings ({scored} scored, {unscored} unscored). "
        f"Newest listing posted at {newest}."
    )
    return {
        "tool": "listing_count",
        "summary": summary,
        "rows": [stats],
    }


# ── Tool 7: skill_demand ──────────────────────────────────────────────


@tool(
    name="skill_demand",
    description=(
        "Returns how often one specific skill appears across listings as explicitly required vs nice-to-have. "
        "Use when the user asks how popular or in-demand a skill is (e.g. 'How in-demand is Python?', 'How often is SQL required?')."
    ),
    parameters={
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill name to check demand for (e.g. 'python', 'aws', 'docker')",
            }
        },
        "required": ["skill"],
    },
)
def skill_demand(
    db_path: str,
    skill: str,
    config: Config | None = None,
) -> dict[str, Any]:
    cfg = config or load_config()
    canonical_skill = _clean_skill_param(skill, cfg)
    if not canonical_skill:
        return {
            "tool": "skill_demand",
            "summary": "No valid skill specified.",
            "rows": [],
        }

    stats = storage.query_skill_demand(db_path, skill=canonical_skill)
    req = stats.get("required_count", 0)
    nice = stats.get("nice_to_have_count", 0)
    sample = stats.get("sample_size", 0)

    summary = (
        f"Skill '{canonical_skill}' appears in {req} listing(s) as required and "
        f"{nice} as nice-to-have across {sample} analyzed listing(s)."
    )
    return {
        "tool": "skill_demand",
        "summary": summary,
        "rows": [stats],
    }
