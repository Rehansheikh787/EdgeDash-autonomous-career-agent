from __future__ import annotations

import argparse
import sys

from edgedash import storage
from edgedash.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Escape hatch to manually clear listing scores for re-scoring (Rule 18)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Clear scores from ALL listings (requires confirmation).",
    )
    group.add_argument(
        "--id",
        dest="listing_id",
        type=str,
        help="Clear score for a specific listing ID.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompt when using --all.",
    )

    args = parser.parse_args()
    config = load_config()
    db_path = config.db_path
    storage.init_db(db_path)

    if args.all:
        if not args.yes:
            try:
                confirm = input("Are you sure you want to clear scores for ALL listings? (y/N): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.")
                sys.exit(1)

            if confirm not in {"y", "yes"}:
                print("Aborted. No scores were cleared.")
                sys.exit(0)

        cleared = storage.clear_scores(db_path, listing_id=None)
        print(f"Cleared scores for {cleared} listing(s).")
    else:
        cleared = storage.clear_scores(db_path, listing_id=args.listing_id)
        if cleared:
            print(f"Cleared score for listing '{args.listing_id}'.")
        else:
            print(f"No scored listing found with ID '{args.listing_id}'.")

    print("Extraction cache was untouched (re-scoring will cost 0 API calls).")
    print("Run 'python run_cycle.py' to score them.")


if __name__ == "__main__":
    main()
