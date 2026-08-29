from __future__ import annotations

from edgedash import storage
from edgedash.config import load_config


def run_diagnostics() -> None:
    config = load_config()
    db_path = config.db_path
    storage.init_db(db_path)

    data = storage.get_diagnostics(db_path)

    print("\n" + "═" * 56)
    print("  EdgeDash — Database Diagnostics (Read-Only)")
    print("═" * 56)

    # 1. Total and source breakdown
    print("\n  1. Listings Overview")
    print("  " + "─" * 52)
    print(f"  Total listings : {data['total_listings']}")
    if data["source_counts"]:
        for source, count in data["source_counts"].items():
            print(f"    • {source:<14} : {count} listing(s)")
    else:
        print("    (no listings found)")

    # 2. Cross-source duplicates
    dupes = data["cross_source_duplicates"]
    print("\n  2. Cross-Source Duplicates (Identical Title + Company)")
    print("  " + "─" * 52)
    if dupes:
        print(f"  Found {len(dupes)} probable cross-source duplicate pair(s):")
        for item in dupes:
            print(f"    • \"{item['title']}\" at \"{item['company']}\"")
            print(f"      Sources: {item['sources']} ({item['total_occurrences']} listings total)")
    else:
        print("  ✓ 0 cross-source duplicates found across different sources.")

    # 3. 5 Most recent listings
    recent = data["recent_listings"]
    print("\n  3. 5 Most Recent Listings")
    print("  " + "─" * 52)
    if recent:
        for idx, item in enumerate(recent, 1):
            source = item.get("source") or "unknown"
            title = item.get("title") or "(no title)"
            company = item.get("company") or "(no company)"
            posted = item.get("posted_at") or "date unknown"
            print(f"  {idx}. [{source}] {title}")
            print(f"     Company: {company} | Posted: {posted}")
    else:
        print("  (no listings recorded)")

    # 4. Data quality check
    issues = data["data_quality_issues"]
    print("\n  4. Data Quality Audit (Missing/Empty URL, Title, or Company)")
    print("  " + "─" * 52)
    if issues:
        print(f"  ⚠️  Found {len(issues)} listing(s) with data quality issues:")
        for bad in issues:
            missing_fields = []
            if not (bad.get("url") or "").strip():
                missing_fields.append("url")
            if not (bad.get("title") or "").strip():
                missing_fields.append("title")
            if not (bad.get("company") or "").strip():
                missing_fields.append("company")
            print(f"    • ID: {bad['id']} [{bad.get('source')}] Missing: {', '.join(missing_fields)}")
    else:
        print("  ✓ All listings have valid non-empty title, company, and url.")

    print("\n" + "═" * 56 + "\n")


if __name__ == "__main__":
    run_diagnostics()
