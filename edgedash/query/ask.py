from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from edgedash import llm, storage
from edgedash.config import Config, load_config
from edgedash.query.guards import check_guards
from edgedash.query.tools import TOOLS


@dataclass(frozen=True)
class Answer:
    text: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    tool_used: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    answerable: bool = True


# ── Prompts ───────────────────────────────────────────────────────────

ROUTING_PROMPT = """You are a precise, deterministic query router for a career intelligence database.
Your only job is to match the user's natural language question to exactly ONE tool from the registry below, or return null if no tool can answer it.

AVAILABLE TOOLS:
{tools_manifest_json}

RULES (STRICT):
1. Select a tool ONLY if its description directly and specifically answers the question.
2. If NO tool directly matches the question, you MUST set "tool" to null. Never guess, never pick the "closest" tool, and never attempt to answer from general knowledge (Rule 45).
3. Do NOT compose SQL, mention table names, or invent parameters (Rule 40).
4. Extract parameters strictly matching the tool's parameter specification. If a parameter is omitted by the user, omit it or use its default.
5. Set "confidence" to "high" if the match is exact and unambiguous, or "low" if uncertain.

USER QUESTION:
\"\"\"{question}\"\"\"

Respond with a valid JSON object matching this schema:
{{
  "tool": string or null,
  "params": object,
  "confidence": "high" or "low"
}}
"""

PHRASING_PROMPT = """You are a factual career intelligence assistant.
Turn the following query results into a concise 2-3 sentence answer to the user's question.

RULES (STRICT - Rule 43):
1. Use ONLY the numbers, company names, and data present in the returned rows below.
2. Do NOT estimate, extrapolate, guess, or add outside industry context.
3. If the rows are empty, state clearly and plainly that the verified database has no matching records for this request.
4. State what data was examined using the tool summary ("across 47 listings from the last 7 days").

USER QUESTION:
\"\"\"{question}\"\"\"

DATA SUMMARY:
{summary}

RETURNED ROWS:
{rows_json}

Respond with a valid JSON object matching this schema:
{{
  "answer": "2-3 concise factual sentences answering the question directly."
}}
"""


def _unanswerable_text() -> str:
    """Standard message listing available questions when no tool matches (Rule 45)."""
    tool_descriptions = "\n".join(
        f"• **{spec.name}**: {spec.description.split('.')[0]}."
        for spec in TOOLS.values()
    )
    return (
        "I cannot answer that question from the verified database. "
        "I only answer questions covered by our deterministic query tools.\n\n"
        f"**Here is what you can ask:**\n{tool_descriptions}"
    )


# ── Main Ask Entrypoint (Rules 40-46) ─────────────────────────────────


def ask(
    question: str,
    session_id: str = "default",
    config: Config | None = None,
    db_path: str | None = None,
) -> Answer:
    """Answer a natural language question through routing, deterministic execution, and phrasing."""
    start_time = time.monotonic()
    cfg = config or load_config()
    target_db = db_path or cfg.db_path

    # 1. Abuse Guards Check (Rule 41, guards)
    guard_res = check_guards(question, session_id=session_id, db_path=target_db, config=cfg)
    if not guard_res.allowed:
        duration = time.monotonic() - start_time
        storage.log_query(
            path=target_db,
            question=question,
            tool_used=None,
            params_json=None,
            answerable=False,
            duration_sec=duration,
            status="rejected",
            rejection_reason=guard_res.rejection_reason,
        )
        msg = guard_res.user_message or _unanswerable_text()
        return Answer(text=msg, rows=[], tool_used=None, params={}, answerable=False)

    sanitized_question = guard_res.sanitized_text

    # 2. ROUTE (Call 1) — Pick tool & parameters
    manifest = [
        {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        }
        for spec in TOOLS.values()
    ]
    route_prompt = ROUTING_PROMPT.format(
        tools_manifest_json=json.dumps(manifest, indent=2),
        question=sanitized_question,
    )

    try:
        route_res = llm.complete_json(
            prompt=route_prompt,
            schema={"tool": (str, type(None)), "params": dict, "confidence": str},
            config=cfg,
        )
    except Exception as exc:
        duration = time.monotonic() - start_time
        storage.log_query(
            path=target_db,
            question=sanitized_question,
            tool_used=None,
            params_json=None,
            answerable=False,
            duration_sec=duration,
            status="error",
            rejection_reason=f"router_error: {exc}",
        )
        return Answer(text=_unanswerable_text(), rows=[], tool_used=None, params={}, answerable=False)

    tool_name = route_res.get("tool")
    params = route_res.get("params") or {}

    # Rule 45: If tool is null or not registered, return fixed help message
    if not tool_name or tool_name not in TOOLS:
        duration = time.monotonic() - start_time
        storage.log_query(
            path=target_db,
            question=sanitized_question,
            tool_used=None,
            params_json=json.dumps(params),
            answerable=False,
            duration_sec=duration,
            status="unanswerable",
        )
        return Answer(text=_unanswerable_text(), rows=[], tool_used=None, params=params, answerable=False)

    # 3. EXECUTE — Run deterministic parameterised tool (Rule 40, 41)
    tool_spec = TOOLS[tool_name]
    try:
        execution_res = tool_spec.func(
            db_path=target_db,
            config=cfg,
            **params,
        )
    except Exception as exc:
        duration = time.monotonic() - start_time
        storage.log_query(
            path=target_db,
            question=sanitized_question,
            tool_used=tool_name,
            params_json=json.dumps(params),
            answerable=False,
            duration_sec=duration,
            status="error",
            rejection_reason=f"execution_error: {exc}",
        )
        return Answer(
            text=f"An error occurred while querying the database: {exc}",
            rows=[],
            tool_used=tool_name,
            params=params,
            answerable=False,
        )

    rows = execution_res.get("rows", [])
    summary = execution_res.get("summary", "")

    # 4. PHRASE (Call 2) — Turn returned rows into prose (Rule 42, 43)
    if not rows:
        phrased_text = f"The database has no matching records for this request ({summary})."
    else:
        # Show top rows to keep prompt compact and avoid token limits
        sample_rows = rows[:10]
        phrase_prompt = PHRASING_PROMPT.format(
            question=sanitized_question,
            summary=summary,
            rows_json=json.dumps(sample_rows, default=str),
        )
        try:
            phrase_res = llm.complete_json(
                prompt=phrase_prompt,
                schema={"answer": str},
                config=cfg,
            )
            phrased_text = phrase_res.get("answer", summary)
        except Exception:
            phrased_text = summary

    duration = time.monotonic() - start_time
    storage.log_query(
        path=target_db,
        question=sanitized_question,
        tool_used=tool_name,
        params_json=json.dumps(params),
        answerable=True,
        duration_sec=duration,
        status="ok",
    )

    return Answer(
        text=phrased_text,
        rows=rows,
        tool_used=tool_name,
        params=params,
        summary=summary,
        answerable=True,
    )


def main() -> None:
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m edgedash.query.ask \"Your natural language question here\"")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"\nQuestion: \"{question}\"")
    answer = ask(question)
    print(f"\nAnswer: {answer.text}")
    if answer.tool_used:
        print(f"Tool used: {answer.tool_used} ({answer.summary})")
    if answer.rows:
        print(f"\nRows returned ({len(answer.rows)}):")
        for idx, row in enumerate(answer.rows[:5], 1):
            print(f"  {idx}. {row}")
    print()


if __name__ == "__main__":
    main()
