from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from edgedash.config import Config

SENIORITY_BANDS = {
    "junior": 0,
    "mid": 1,
    "senior": 2,
    "lead": 3,
}


def score_listing(
    listing: dict[str, Any],
    facts: dict[str, Any],
    config: Config,
    widen_distribution: bool = False,
) -> dict[str, Any]:
    """Calculate deterministic fit score (0-100) and structured reason."""
    # ── 1. Skill Match (0.0 - 1.0) ────────────────────────────────────
    my_skills = {str(s).lower().strip() for s in (config.my_skills or []) if str(s).strip()}
    req_skills = [str(s).lower().strip() for s in facts.get("required_skills", []) if str(s).strip()]
    nice_skills = [str(s).lower().strip() for s in facts.get("nice_to_have", []) if str(s).strip()]

    matched_req = [s for s in req_skills if s in my_skills]
    matched_nice = [s for s in nice_skills if s in my_skills]
    missing_req = [s for s in req_skills if s not in my_skills]

    if req_skills:
        req_fraction = len(matched_req) / len(req_skills)
        if nice_skills:
            nice_fraction = len(matched_nice) / len(nice_skills)
            # Nice-to-have counts at 1/3 weight
            skill_match = min(1.0, (len(matched_req) + (1 / 3) * len(matched_nice)) / (len(req_skills) + (1 / 3) * len(nice_skills)))
        else:
            skill_match = req_fraction
    elif nice_skills:
        skill_match = len(matched_nice) / len(nice_skills)
    else:
        skill_match = 0.5  # Explicit empty-required-skills neutral baseline

    if widen_distribution:
        skill_match = skill_match ** 1.35

    skill_match = max(0.0, min(1.0, skill_match))

    # ── 2. Seniority Fit (0.0 - 1.0) ──────────────────────────────────
    target_sen = getattr(config, "target_seniority", "mid").lower().strip()
    target_idx = SENIORITY_BANDS.get(target_sen, 1)

    fact_sen = str(facts.get("seniority") or "unknown").lower().strip()
    if fact_sen in SENIORITY_BANDS:
        fact_idx = SENIORITY_BANDS[fact_sen]
        diff = abs(fact_idx - target_idx)
        if diff == 0:
            seniority_fit = 1.0
        elif diff == 1:
            seniority_fit = 0.35 if widen_distribution else 0.6
        elif diff == 2:
            seniority_fit = 0.05 if widen_distribution else 0.25
        else:
            seniority_fit = 0.0
    else:
        seniority_fit = 0.5  # Unknown seniority

    # ── 3. Location Fit (0.0 - 1.0) ───────────────────────────────────
    remote_ok = facts.get("remote_ok")
    target_city = (config.target_city or "").lower().strip()
    target_country = (getattr(config, "target_country", "") or "").lower().strip()
    target_locs = [str(loc).lower().strip() for loc in getattr(config, "target_locations", []) if loc]
    if target_city and target_city not in target_locs:
        target_locs.append(target_city)
    if target_country and target_country not in target_locs:
        target_locs.append(target_country)

    listing_loc = str(listing.get("location") or "").lower().strip()

    # Remote job or worldwide remote
    is_remote_listing = (
        remote_ok is True
        or "remote" in listing_loc
        or "worldwide" in listing_loc
        or "anywhere" in listing_loc
    )

    # Location match against target preferences
    is_location_match = bool(listing_loc) and any(
        (loc in listing_loc or listing_loc in loc)
        for loc in target_locs
        if loc
    )

    # Foreign country restriction check (e.g. "Remote in Deutschland", "UK - Remote")
    foreign_restrictions = [
        "deutschland", "germany", "uk", "united kingdom", "us only", "usa only",
        "austria", "switzerland", "france", "spain", "netherlands", "berlin", "munich",
        "london", "emea", "latam"
    ]
    active_restrictions = [r for r in foreign_restrictions if not any(r in tl for tl in target_locs)]
    is_foreign_country_restricted = any(r in listing_loc for r in active_restrictions)

    if is_foreign_country_restricted and not is_location_match:
        location_fit = 0.1  # Clearly elsewhere and not matching
    elif is_location_match or is_remote_listing:
        location_fit = 1.0
    elif remote_ok is None and (not listing_loc or listing_loc in {"unknown", "n/a", "none"}):
        location_fit = 0.5
    else:
        location_fit = 0.1  # Clearly elsewhere and not remote

    # ── 4. Recency (0.0 - 1.0) ────────────────────────────────────────
    posted_raw = listing.get("posted_at")
    age_days: float | None = None
    if posted_raw:
        try:
            if isinstance(posted_raw, (int, float)):
                posted_dt = datetime.fromtimestamp(posted_raw, tz=timezone.utc)
            else:
                posted_str = str(posted_raw).replace("Z", "+00:00")
                posted_dt = datetime.fromisoformat(posted_str)
                if posted_dt.tzinfo is None:
                    posted_dt = posted_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            age_days = max(0.0, (now_dt - posted_dt).total_seconds() / 86400.0)
            if age_days >= 30.0:
                recency = 0.0
            else:
                recency = 1.0 - (age_days / 30.0)
        except Exception:
            recency = 0.5
    else:
        recency = 0.5

    recency = max(0.0, min(1.0, recency))

    # ── Weighted Sum ──────────────────────────────────────────────────
    w_skill = getattr(config, "weight_skill_match", 0.45)
    w_sen = getattr(config, "weight_seniority_fit", 0.25)
    w_loc = getattr(config, "weight_location_fit", 0.15)
    w_rec = getattr(config, "weight_recency", 0.15)

    total_weight = w_skill + w_sen + w_loc + w_rec or 1.0
    weighted_total = (
        skill_match * w_skill +
        seniority_fit * w_sen +
        location_fit * w_loc +
        recency * w_rec
    ) / total_weight

    score = int(round(weighted_total * 100))
    score = max(0, min(100, score))

    components = {
        "skill_match": round(skill_match, 4),
        "seniority_fit": round(seniority_fit, 4),
        "location_fit": round(location_fit, 4),
        "recency": round(recency, 4),
    }

    reason = build_reason(
        components=components,
        facts=facts,
        config=config,
        matched_req=matched_req,
        missing_req=missing_req,
        age_days=age_days,
    )

    return {
        "score": score,
        "reason": reason,
        "components": components,
    }


def build_reason(
    components: dict[str, float],
    facts: dict[str, Any],
    config: Config,
    matched_req: list[str] | None = None,
    missing_req: list[str] | None = None,
    age_days: float | None = None,
) -> str:
    """Build human-readable reason string assembled strictly from numbers and facts."""
    req_skills = facts.get("required_skills") or []
    if matched_req is None:
        my_skills = {str(s).lower().strip() for s in (config.my_skills or [])}
        matched_req = [s for s in req_skills if str(s).lower().strip() in my_skills]
    if missing_req is None:
        my_skills = {str(s).lower().strip() for s in (config.my_skills or [])}
        missing_req = [s for s in req_skills if str(s).lower().strip() not in my_skills]

    parts: list[str] = []

    # Skill segment
    if req_skills:
        parts.append(f"{len(matched_req)}/{len(req_skills)} required skills")
    else:
        parts.append("no required skills listed")

    # Seniority segment
    sen_score = components.get("seniority_fit", 0.5)
    if sen_score == 1.0:
        parts.append("seniority fits")
    elif sen_score == 0.6:
        parts.append("1 level away")
    elif sen_score == 0.25:
        parts.append("2 levels away")
    elif sen_score == 0.0:
        parts.append("seniority mismatch")
    else:
        parts.append("seniority unknown")

    # Location segment
    loc_score = components.get("location_fit", 0.5)
    if facts.get("remote_ok") is True:
        parts.append("remote")
    elif loc_score == 1.0:
        parts.append("matches target city")
    elif loc_score == 0.5:
        parts.append("location unstated")
    else:
        parts.append("onsite elsewhere")

    # Recency segment
    if age_days is not None:
        if age_days < 1.0:
            parts.append("posted today")
        else:
            parts.append(f"posted {int(age_days)}d ago")
    else:
        parts.append("post date unknown")

    # Gap segment (Rule 19)
    if missing_req:
        gaps_preview = ", ".join(missing_req[:3])
        parts.append(f"gap: {gaps_preview}")
    else:
        parts.append("no skill gaps")

    return " · ".join(parts)
