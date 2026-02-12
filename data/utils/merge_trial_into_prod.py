import argparse
import sqlite3
from pathlib import Path


def resolve_data_dir() -> Path:
    # Script lives in data/utils, so parent is the data directory.
    return Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    data_dir = resolve_data_dir()
    parser = argparse.ArgumentParser(
        description="Merge non-duplicate restaurants from trial DB into production restaurants table."
    )
    parser.add_argument(
        "--trial-db-path",
        default=str(data_dir / "restaurants_trial.db"),
        help="Trial DB path (default: <repo>/data/restaurants_trial.db)",
    )
    parser.add_argument(
        "--prod-db-path",
        default=str(data_dir / "restaurants.db"),
        help="Production DB path (default: <repo>/data/restaurants.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview counts without writing changes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trial_db = Path(args.trial_db_path).expanduser().resolve()
    prod_db = Path(args.prod_db_path).expanduser().resolve()
    if not trial_db.exists():
        raise SystemExit(f"Trial DB not found: {trial_db}")
    if not prod_db.exists():
        raise SystemExit(f"Prod DB not found: {prod_db}")

    conn = sqlite3.connect(str(prod_db))
    try:
        conn.execute("ATTACH DATABASE ? AS trial", (str(trial_db),))

        total_trial = conn.execute("SELECT COUNT(*) FROM trial.restaurants").fetchone()[0]
        mergeable = conn.execute(
            """
            SELECT COUNT(*)
            FROM trial.restaurants t
            LEFT JOIN restaurants p ON p.google_place_id = t.google_place_id
            WHERE p.google_place_id IS NULL
            """
        ).fetchone()[0]

        if args.dry_run:
            print("=== Dry Run Merge Plan ===")
            print(f"trial_db: {trial_db}")
            print(f"prod_db: {prod_db}")
            print(f"trial_restaurants_total: {total_trial}")
            print(f"restaurants_mergeable_by_place_id: {mergeable}")
            print(f"restaurants_already_present_or_duplicate: {total_trial - mergeable}")
            print("No writes committed (--dry-run).")
            return

        before_changes = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO restaurants (
                google_place_id, name, latitude, longitude, address, price_level, business_status
            )
            SELECT
                google_place_id, name, latitude, longitude, address, price_level, business_status
            FROM trial.restaurants
            """
        )
        inserted = conn.total_changes - before_changes
        conn.commit()

        print("=== Merge Summary ===")
        print(f"trial_db: {trial_db}")
        print(f"prod_db: {prod_db}")
        print(f"trial_restaurants_total: {total_trial}")
        print(f"restaurants_inserted_into_prod: {inserted}")
        print(f"restaurants_already_present_or_duplicate: {total_trial - inserted}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
