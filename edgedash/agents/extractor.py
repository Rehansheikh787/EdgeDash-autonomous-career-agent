from __future__ import annotations

import hashlib
from typing import Any

from edgedash import storage
from edgedash.config import Config
from edgedash.llm import complete_json

# ── Extraction Schema (Rule 16: Fact extraction only, NO score field) ──
EXTRACTION_SCHEMA: dict[str, Any] = {
    "required_skills": list,
    "nice_to_have": list,
    "seniority": str,
    "years_required": (int, type(None)),
    "remote_ok": (bool, type(None)),
}

VALID_SENIORITIES = {"junior", "mid", "senior", "lead", "unknown"}

# ── Extraction Prompt (Objective factual reader, no candidate profile) ─
EXTRACTION_PROMPT = """You are an objective data extraction system.
Read the following job description and extract only the factual information stated directly in the text.

CRITICAL INSTRUCTIONS:
- Extract ONLY what the listing explicitly mentions.
- Do NOT infer, guess, extrapolate, or evaluate a candidate.
- If a detail is not stated, set the field to null or an empty list [].
- Never include a score, ranking, or qualitative judgment.

Return a JSON object with EXACTLY these fields:
- "required_skills": list of strings (technical skills, tools, or frameworks explicitly required)
- "nice_to_have": list of strings (skills explicitly listed as preferred/optional/plus)
- "seniority": string (must be exactly one of: "junior", "mid", "senior", "lead", "unknown")
- "years_required": integer or null (minimum years of experience required, or null if not stated)
- "remote_ok": boolean or null (true if remote work is allowed/offered, false if strictly on-site, null if not mentioned)

Job Title: {title}
Job Description:
\"\"\"
{description}
\"\"\"
"""


def extract(
    listing: dict[str, Any],
    db_path: str,
    config: Config | None = None,
) -> dict[str, Any]:
    """Extract factual job attributes with hash-based caching."""
    desc = (listing.get("description") or "").strip()
    desc_hash = hashlib.sha256(desc.encode("utf-8")).hexdigest()

    # Rule 18: Check extraction cache first
    cached = storage.get_extraction(db_path, desc_hash)
    if cached is not None:
        return cached

    prompt = EXTRACTION_PROMPT.format(
        title=listing.get("title") or "Untitled",
        description=desc,
    )

    raw_result = complete_json(prompt, EXTRACTION_SCHEMA, config=config)

    # Normalise extracted values
    req_skills = [
        str(s).strip().lower()
        for s in raw_result.get("required_skills", [])
        if str(s).strip()
    ]
    nice_skills = [
        str(s).strip().lower()
        for s in raw_result.get("nice_to_have", [])
        if str(s).strip()
    ]

    raw_sen = str(raw_result.get("seniority") or "").strip().lower()
    seniority = raw_sen if raw_sen in VALID_SENIORITIES else "unknown"

    years_req = raw_result.get("years_required")
    years_val = int(years_req) if isinstance(years_req, (int, float)) else None

    remote_val = (
        bool(raw_result.get("remote_ok"))
        if isinstance(raw_result.get("remote_ok"), bool)
        else None
    )

    normalised: dict[str, Any] = {
        "required_skills": req_skills,
        "nice_to_have": nice_skills,
        "seniority": seniority,
        "years_required": years_val,
        "remote_ok": remote_val,
    }

    # Store in cache per Rule 18
    storage.set_extraction(db_path, desc_hash, normalised)
    return normalised
