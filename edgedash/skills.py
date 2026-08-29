from __future__ import annotations

import re
import sys
from collections import Counter
from typing import Any

from edgedash import storage
from edgedash.config import load_config


def canonical(raw: str, aliases: dict[str, str] | None = None) -> str:
    """Normalize and canonicalize a raw skill string (deterministic, pure function)."""
    if not raw or not isinstance(raw, str):
        return ""

    # 1. Lowercase
    text = raw.lower()

    # 2. Drop parenthetical qualifiers e.g. "kubernetes (eks)" -> "kubernetes"
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\{[^}]*\}", "", text)

    # 3. Collapse multiple whitespace characters
    text = re.sub(r"\s+", " ", text).strip()

    # 4. Strip surrounding punctuation
    text = text.strip("\"'.,;:-_/\\`~*!|#")

    # 5. Collapse whitespace again after punctuation strip
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return ""

    # 6. Apply alias map
    if aliases:
        # Check direct match against normalized alias map
        alias_match = aliases.get(text)
        if alias_match:
            return alias_match.strip().lower()

    return text


def audit_skills() -> None:
    """Audit extracted skills from database to discover collisions and typos (Rule 23)."""
    config = load_config()
    db_path = config.db_path
    storage.init_db(db_path)

    raw_skills = storage.get_all_extracted_skills(db_path)
    aliases = config.skill_aliases or {}

    print("\n" + "═" * 60)
    print("  EdgeDash — Extracted Skills Audit (Read-Only)")
    print("═" * 60)
    print(f"  Total raw skill mentions in database: {len(raw_skills)}")

    if not raw_skills:
        print("\n  (No extracted skills found in extraction cache yet.)")
        print("  Run 'python run_cycle.py' to score listings and populate cache.\n")
        return

    counts = Counter(raw_skills)
    total_unique = len(counts)
    print(f"  Unique raw skill terms: {total_unique}\n")

    # 1. Top 40 raw skills with counts and canonical mappings
    print("  1. Top 40 Most Common Raw Skills & Canonical Mappings")
    print("  " + "─" * 56)
    print(f"  {'Count':<7} {'Raw Skill String':<26} → {'Canonical Form'}")
    print("  " + "─" * 56)
    for raw_str, cnt in counts.most_common(40):
        canon_str = canonical(raw_str, aliases)
        alias_note = f" (aliased from map)" if raw_str.lower() != canon_str else ""
        print(f"  {cnt:<7} {raw_str:<26} → {canon_str}{alias_note}")

    # 2. Singletons (seen only once — candidates for typos/junk)
    singletons = [raw_str for raw_str, cnt in counts.items() if cnt == 1]
    print("\n  2. Single-Occurrence Skills (Seen Only Once — Potential Typos/Junk)")
    print("  " + "─" * 56)
    if singletons:
        print(f"  Found {len(singletons)} single-occurrence skill(s):")
        for idx, item in enumerate(sorted(singletons)[:50], 1):
            canon = canonical(item, aliases)
            print(f"    {idx:>2}. \"{item}\" → \"{canon}\"")
        if len(singletons) > 50:
            print(f"    ... and {len(singletons) - 50} more.")
    else:
        print("  ✓ No single-occurrence skills found.")

    print("\n" + "═" * 60 + "\n")


if __name__ == "__main__":
    if "--audit" in sys.argv:
        audit_skills()
    else:
        print("Usage: python -m edgedash.skills --audit")
