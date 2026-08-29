from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class Config:
    target_role: str = ""
    target_city: str = ""
    target_country: str = ""
    target_locations: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    my_skills: list[str] = field(default_factory=list)
    experience_years: int = 0
    db_path: str = "edgedash.db"
    min_fit_score: int = 0
    sources: list[str] = field(default_factory=lambda: ["arbeitnow"])
    use_mock_fetcher: bool = False
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    target_seniority: str = "mid"
    score_batch_size: int = 25
    weight_skill_match: float = 0.45
    weight_seniority_fit: float = 0.25
    weight_location_fit: float = 0.15
    weight_recency: float = 0.15
    skill_aliases: dict[str, str] = field(default_factory=dict)
    fetch_interval_hours: float = 6.0
    max_fetch_pages: int = 5
    max_fetch_listings: int = 100
    score_max_seconds: int = 120
    gap_max_seconds: int = 30
    min_score_spread: int = 10
    min_score_stdev: float = 5.0
    max_empty_extraction_pct: float = 20.0
    max_skills_per_listing: int = 50
    min_gap_sample: int = 3
    max_data_age_days: float = 3.0
    max_daily_queries: int = 200


def load_config(path: Path | None = None) -> Config:
    _load_dotenv()
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Config file not found: {config_path.resolve()}. "
            "Copy config.yaml from the repo root and edit it."
        )

    raw = _parse_simple_yaml(config_path.read_text(encoding="utf-8"))
    sources = _as_str_list(raw.get("sources", ["arbeitnow"]))
    if not sources:
        sources = ["arbeitnow"]

    raw_locs = _as_str_list(raw.get("target_locations", []))
    target_city = str(raw.get("target_city", ""))
    target_country = str(raw.get("target_country", ""))
    if not raw_locs and target_city:
        raw_locs = [target_city]
    if target_country and target_country not in raw_locs:
        raw_locs.append(target_country)

    return Config(
        target_role=str(raw.get("target_role", "")),
        target_city=target_city,
        target_country=target_country,
        target_locations=raw_locs,
        keywords=_as_str_list(raw.get("keywords", [])),
        my_skills=_as_str_list(raw.get("my_skills", [])),
        experience_years=int(raw.get("experience_years", 0)),
        db_path=str(raw.get("db_path", "edgedash.db")),
        min_fit_score=int(raw.get("min_fit_score", 0)),
        sources=sources,
        use_mock_fetcher=bool(raw.get("use_mock_fetcher", False)),
        llm_provider=str(raw.get("llm_provider", "gemini")),
        llm_model=str(raw.get("llm_model", "gemini-2.5-flash")),
        target_seniority=str(raw.get("target_seniority", "mid")),
        score_batch_size=int(raw.get("score_batch_size", 25)),
        weight_skill_match=float(raw.get("weight_skill_match", 0.45)),
        weight_seniority_fit=float(raw.get("weight_seniority_fit", 0.25)),
        weight_location_fit=float(raw.get("weight_location_fit", 0.15)),
        weight_recency=float(raw.get("weight_recency", 0.15)),
        skill_aliases=_as_str_dict(raw.get("skill_aliases", {})),
        fetch_interval_hours=float(raw.get("fetch_interval_hours", 6.0)),
        max_fetch_pages=int(raw.get("max_fetch_pages", 5)),
        max_fetch_listings=int(raw.get("max_fetch_listings", 100)),
        score_max_seconds=int(raw.get("score_max_seconds", 120)),
        gap_max_seconds=int(raw.get("gap_max_seconds", 30)),
        min_score_spread=int(raw.get("min_score_spread", 10)),
        min_score_stdev=float(raw.get("min_score_stdev", 5.0)),
        max_empty_extraction_pct=float(raw.get("max_empty_extraction_pct", 20.0)),
        max_skills_per_listing=int(raw.get("max_skills_per_listing", 50)),
        min_gap_sample=int(raw.get("min_gap_sample", 3)),
        max_data_age_days=float(raw.get("max_data_age_days", 3.0)),
        max_daily_queries=int(raw.get("max_daily_queries", 200)),
    )


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, dict):
        return [str(k) for k in value.keys()]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _as_str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k).lower().strip(): str(v).lower().strip() for k, v in value.items()}


def _parse_simple_yaml(text: str) -> dict[str, object]:
    result: dict[str, object] = {}
    current_key: str | None = None
    current_type: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.split("#")[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if indent > 0 and current_key:
            if stripped.startswith("- "):
                if current_type != "list":
                    current_type = "list"
                    result[current_key] = []
                items = result[current_key]
                if isinstance(items, list):
                    items.append(_strip_quotes(stripped[2:].strip()))
                continue
            elif ":" in stripped:
                if current_type != "dict":
                    current_type = "dict"
                    result[current_key] = {}
                sub_k, _, sub_v = stripped.partition(":")
                sub_dict = result[current_key]
                if isinstance(sub_dict, dict):
                    sub_dict[sub_k.strip().lower()] = _strip_quotes(sub_v.strip().lower())
                continue

        key, sep, value = stripped.partition(":")
        if not sep:
            continue

        key = key.strip()
        value = value.strip()
        if not value:
            current_key = key
            current_type = None
            result[key] = []
            continue

        current_key = None
        current_type = None
        result[key] = _coerce_scalar(_strip_quotes(value))

    return result


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _coerce_scalar(value: str) -> object:
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    try:
        if "." in value:
            return float(value)
    except ValueError:
        pass
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if sep and key.strip() not in os.environ:
            os.environ[key.strip()] = _strip_quotes(value.strip())

