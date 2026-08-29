from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from edgedash.config import Config


@dataclass(frozen=True)
class CheckResult:
    """Individual verification check outcome (Rule 34, 37)."""
    name: str
    passed: bool
    observed: Any
    threshold: Any
    message: str


@dataclass(frozen=True)
class Verdict:
    """Aggregated plausibility verdict over all verification checks (Rule 34-38)."""
    passed: bool
    failed_checks: list[CheckResult]
    summary: str
    results: list[CheckResult] = field(default_factory=list)


def check_score_spread(scores: list[int | float], config: Config) -> CheckResult:
    """Check score spread & variance to catch score inflation/compression failure modes (Rule 35, 39)."""
    if len(scores) < 5:
        return CheckResult(
            name="score_spread",
            passed=True,
            observed={"count": len(scores)},
            threshold={"min_count": 5},
            message=f"Trivially passed: fewer than 5 scores ({len(scores)})",
        )

    spread = max(scores) - min(scores)
    stdev = statistics.stdev(scores)
    min_spread = getattr(config, "min_score_spread", 10)
    min_stdev = getattr(config, "min_score_stdev", 5.0)

    if spread < min_spread:
        return CheckResult(
            name="score_spread",
            passed=False,
            observed={"spread": spread, "stdev": round(stdev, 2)},
            threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
            message=f"Score spread {spread} < threshold {min_spread} (scores too compressed)",
        )

    if stdev < min_stdev:
        return CheckResult(
            name="score_spread",
            passed=False,
            observed={"spread": spread, "stdev": round(stdev, 2)},
            threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
            message=f"Score standard deviation {stdev:.2f} < threshold {min_stdev} (lack of variance)",
        )

    return CheckResult(
        name="score_spread",
        passed=True,
        observed={"spread": spread, "stdev": round(stdev, 2)},
        threshold={"min_score_spread": min_spread, "min_score_stdev": min_stdev},
        message=f"Score spread ({spread}) and stdev ({stdev:.2f}) are healthy",
    )


def check_extraction_sanity(
    facts_list: list[dict[str, Any]],
    config: Config,
) -> CheckResult:
    """Check extraction plausibility to catch broken LLM schemas or paragraph-as-skill dumping (Rule 35, 39)."""
    if not facts_list:
        return CheckResult(
            name="extraction_sanity",
            passed=True,
            observed={"total": 0, "empty_pct": 0.0, "max_skills": 0},
            threshold={},
            message="Trivially passed: 0 facts to verify",
        )

    max_empty_pct = getattr(config, "max_empty_extraction_pct", 20.0)
    max_skills_limit = getattr(config, "max_skills_per_listing", 20)

    empty_count = sum(1 for f in facts_list if not f.get("required_skills"))
    empty_pct = round((empty_count / len(facts_list)) * 100.0, 1)
    max_skills_found = max((len(f.get("required_skills") or []) for f in facts_list), default=0)

    if empty_pct > max_empty_pct:
        return CheckResult(
            name="extraction_sanity",
            passed=False,
            observed={"empty_pct": empty_pct, "empty_count": empty_count, "total": len(facts_list)},
            threshold={"max_empty_extraction_pct": max_empty_pct},
            message=f"Empty required_skills rate {empty_pct}% ({empty_count}/{len(facts_list)}) exceeds threshold {max_empty_pct}%",
        )

    if max_skills_found > max_skills_limit:
        return CheckResult(
            name="extraction_sanity",
            passed=False,
            observed={"max_skills_found": max_skills_found},
            threshold={"max_skills_per_listing": max_skills_limit},
            message=f"Max skills per listing {max_skills_found} exceeds threshold {max_skills_limit} (possible sentence dump)",
        )

    return CheckResult(
        name="extraction_sanity",
        passed=True,
        observed={"empty_pct": empty_pct, "max_skills_found": max_skills_found},
        threshold={"max_empty_extraction_pct": max_empty_pct, "max_skills_per_listing": max_skills_limit},
        message=f"Extraction sanity OK: {empty_pct}% empty, max {max_skills_found} skills/listing",
    )


def check_gap_sample_size(
    gaps: list[dict[str, Any]],
    config: Config,
) -> CheckResult:
    """Check that top-ranked career skill gap meets minimal sample size to avoid ranking a rumour (Rule 35, 39)."""
    min_sample = getattr(config, "min_gap_sample", 3)
    if not gaps:
        return CheckResult(
            name="gap_sample_size",
            passed=True,
            observed={"top_sample": 0},
            threshold={"min_gap_sample": min_sample},
            message="Trivially passed: 0 gaps reported",
        )

    top_gap = gaps[0]
    top_sample = top_gap.get("listings_blocked", 0)
    top_skill = top_gap.get("skill", "unknown")

    if top_sample < min_sample:
        return CheckResult(
            name="gap_sample_size",
            passed=False,
            observed={"top_skill": top_skill, "top_sample": top_sample},
            threshold={"min_gap_sample": min_sample},
            message=f"Top gap '{top_skill}' backed by only {top_sample} listing(s) < minimum threshold {min_sample}",
        )

    return CheckResult(
        name="gap_sample_size",
        passed=True,
        observed={"top_skill": top_skill, "top_sample": top_sample},
        threshold={"min_gap_sample": min_sample},
        message=f"Top gap '{top_skill}' backed by {top_sample} listings >= {min_sample}",
    )


def check_freshness(
    latest_fetch_at: str | None,
    config: Config,
    now: datetime,
) -> CheckResult:
    """Check that listing data age does not exceed max days (Rule 35, 39)."""
    max_age_days = getattr(config, "max_data_age_days", 3.0)
    if not latest_fetch_at:
        return CheckResult(
            name="data_freshness",
            passed=False,
            observed={"latest_fetch_at": None, "age_days": None},
            threshold={"max_data_age_days": max_age_days},
            message="No fetch timestamp found (empty dataset)",
        )

    try:
        fetch_str = str(latest_fetch_at).replace("Z", "+00:00")
        fetch_dt = datetime.fromisoformat(fetch_str)
        if fetch_dt.tzinfo is None:
            fetch_dt = fetch_dt.replace(tzinfo=timezone.utc)
        now_utc = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        diff_seconds = (now_utc - fetch_dt).total_seconds()
        age_days = max(0.0, diff_seconds / 86400.0)
    except Exception as exc:
        return CheckResult(
            name="data_freshness",
            passed=False,
            observed={"latest_fetch_at": latest_fetch_at, "error": str(exc)},
            threshold={"max_data_age_days": max_age_days},
            message=f"Failed parsing fetch timestamp '{latest_fetch_at}': {exc}",
        )

    if age_days > max_age_days:
        return CheckResult(
            name="data_freshness",
            passed=False,
            observed={"age_days": round(age_days, 2), "latest_fetch_at": latest_fetch_at},
            threshold={"max_data_age_days": max_age_days},
            message=f"Data age {age_days:.1f} days exceeds max allowed age {max_age_days} days",
        )

    return CheckResult(
        name="data_freshness",
        passed=True,
        observed={"age_days": round(age_days, 2), "latest_fetch_at": latest_fetch_at},
        threshold={"max_data_age_days": max_age_days},
        message=f"Data freshness OK: age {age_days:.1f} days <= {max_age_days} days",
    )


def run_all_checks(
    scores: list[int | float],
    facts_list: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    latest_fetch_at: str | None,
    config: Config,
    now: datetime,
) -> Verdict:
    """Run all verification checks deterministically and compile a Verdict (Rule 34, 35)."""
    results: list[CheckResult] = [
        check_score_spread(scores, config),
        check_extraction_sanity(facts_list, config),
        check_gap_sample_size(gaps, config),
        check_freshness(latest_fetch_at, config, now=now),
    ]

    failed_checks = [r for r in results if not r.passed]
    passed = (len(failed_checks) == 0)

    if passed:
        summary = f"All {len(results)} verification check(s) passed"
    else:
        names = ", ".join(c.name for c in failed_checks)
        summary = f"{len(failed_checks)} of {len(results)} check(s) failed: {names}"

    return Verdict(
        passed=passed,
        failed_checks=failed_checks,
        summary=summary,
        results=results,
    )
