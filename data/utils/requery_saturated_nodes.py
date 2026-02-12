import argparse
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

GOOGLE_API_URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.location,"
    "places.priceLevel,"
    "places.businessStatus,"
    "places.formattedAddress"
)


def resolve_data_dir() -> Path:
    # Script lives in data/utils, so parent is the data directory.
    return Path(__file__).resolve().parent.parent


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Requery saturated trial ingestion cells with an extra center call per split node"
    )
    parser.add_argument(
        "--db-path",
        default=str(resolve_data_dir() / "restaurants_trial.db"),
        help="Trial DB path (default: <repo>/data/restaurants_trial.db)",
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=None,
        help="Specific ingestion_runs.id to process (default: latest run)",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help="Optional hard cap for extra calls in this remediation run.",
    )
    parser.add_argument(
        "--request-timeout-sec",
        type=float,
        default=12.0,
        help="HTTP timeout for Google Places requests.",
    )
    parser.add_argument(
        "--request-delay-sec",
        type=float,
        default=0.1,
        help="Delay between extra API calls.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned extra calls without hitting API.",
    )
    parser.add_argument(
        "--include-already-processed",
        action="store_true",
        help="Include saturated cells already processed by this remediation script.",
    )
    return parser.parse_args()


def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_saturation_rechecks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            parent_cell_id INTEGER NOT NULL,
            parent_cell_key TEXT NOT NULL,
            requested_at TEXT NOT NULL,
            responded_at TEXT,
            http_status INTEGER,
            query_radius_m REAL NOT NULL,
            result_count INTEGER,
            inserted_count INTEGER,
            duplicate_count INTEGER,
            error_message TEXT,
            UNIQUE(run_id, parent_cell_id),
            FOREIGN KEY(run_id) REFERENCES ingestion_runs(id),
            FOREIGN KEY(parent_cell_id) REFERENCES ingestion_cells(id)
        )
        """
    )
    conn.commit()


def latest_run_id(conn: sqlite3.Connection) -> Optional[int]:
    row = conn.execute("SELECT MAX(id) FROM ingestion_runs").fetchone()
    if row is None:
        return None
    return row[0]


def load_saturated_split_nodes(
    conn: sqlite3.Connection,
    run_id: int,
    include_already_processed: bool,
) -> List[sqlite3.Row]:
    if include_already_processed:
        return conn.execute(
            """
            SELECT c.*
            FROM ingestion_cells c
            WHERE c.run_id = ? AND c.is_saturated = 1 AND c.status = 'split'
            ORDER BY c.id
            """,
            (run_id,),
        ).fetchall()

    return conn.execute(
        """
        SELECT c.*
        FROM ingestion_cells c
        WHERE c.run_id = ?
          AND c.is_saturated = 1
          AND c.status = 'split'
          AND NOT EXISTS (
              SELECT 1
              FROM ingestion_saturation_rechecks r
              WHERE r.run_id = c.run_id
                AND r.parent_cell_id = c.id
                AND r.error_message IS NULL
          )
        ORDER BY c.id
        """,
        (run_id,),
    ).fetchall()


def normalize_place(place: Dict[str, Any]) -> Optional[Tuple[str, str, float, float, str, Optional[int], str]]:
    place_id = place.get("id")
    location = place.get("location") or {}
    lat = location.get("latitude")
    lng = location.get("longitude")
    if not place_id or lat is None or lng is None:
        return None

    name = (place.get("displayName") or {}).get("text") or "Unnamed"
    address = place.get("formattedAddress") or ""
    business_status = place.get("businessStatus") or "OPERATIONAL"
    price_level = place.get("priceLevel")

    return (
        str(place_id),
        str(name).strip() or "Unnamed",
        float(lat),
        float(lng),
        str(address),
        int(price_level) if isinstance(price_level, int) else None,
        str(business_status),
    )


def load_existing_place_ids(conn: sqlite3.Connection) -> Set[str]:
    rows = conn.execute("SELECT google_place_id FROM restaurants").fetchall()
    return {str(r[0]) for r in rows}


def insert_places(conn: sqlite3.Connection, places: List[Dict[str, Any]], seen: Set[str]) -> Tuple[int, int]:
    inserted = 0
    duplicates = 0
    cur = conn.cursor()

    for raw_place in places:
        row = normalize_place(raw_place)
        if row is None:
            continue

        place_id = row[0]
        if place_id in seen:
            duplicates += 1
            continue

        cur.execute(
            """
            INSERT OR IGNORE INTO restaurants (
                google_place_id, name, latitude, longitude, address, price_level, business_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )
        seen.add(place_id)
        if cur.rowcount and cur.rowcount > 0:
            inserted += 1
        else:
            duplicates += 1

    conn.commit()
    return inserted, duplicates


def fetch_places(api_key: str, lat: float, lng: float, radius_m: float, timeout_sec: float) -> Tuple[List[Dict[str, Any]], int]:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    payload = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        },
        "includedPrimaryTypes": ["restaurant"],
        "maxResultCount": 20,
    }
    resp = requests.post(GOOGLE_API_URL, json=payload, headers=headers, timeout=timeout_sec)
    status_code = resp.status_code
    resp.raise_for_status()
    data = resp.json()
    return data.get("places", []), status_code


def upsert_recheck_row(
    conn: sqlite3.Connection,
    run_id: int,
    parent_cell_id: int,
    parent_cell_key: str,
    requested_at: str,
    responded_at: Optional[str],
    http_status: Optional[int],
    query_radius_m: float,
    result_count: Optional[int],
    inserted_count: Optional[int],
    duplicate_count: Optional[int],
    error_message: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO ingestion_saturation_rechecks (
            run_id, parent_cell_id, parent_cell_key, requested_at, responded_at, http_status,
            query_radius_m, result_count, inserted_count, duplicate_count, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, parent_cell_id) DO UPDATE SET
            requested_at = excluded.requested_at,
            responded_at = excluded.responded_at,
            http_status = excluded.http_status,
            query_radius_m = excluded.query_radius_m,
            result_count = excluded.result_count,
            inserted_count = excluded.inserted_count,
            duplicate_count = excluded.duplicate_count,
            error_message = excluded.error_message
        """,
        (
            run_id,
            parent_cell_id,
            parent_cell_key,
            requested_at,
            responded_at,
            http_status,
            query_radius_m,
            result_count,
            inserted_count,
            duplicate_count,
            error_message,
        ),
    )
    conn.commit()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path).expanduser()
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    api_key = os.getenv("GOOGLE_PLACES_API_KEY")

    conn = open_db(db_path)
    try:
        create_tables(conn)

        run_id = args.run_id if args.run_id is not None else latest_run_id(conn)
        if run_id is None:
            raise SystemExit("No ingestion runs found in the provided DB.")

        nodes = load_saturated_split_nodes(
            conn,
            run_id=run_id,
            include_already_processed=args.include_already_processed,
        )

        if args.max_calls is not None:
            max_calls = max(0, int(args.max_calls))
            nodes = nodes[:max_calls]
        planned_calls = len(nodes)

        print("=== Saturated Recheck Plan ===")
        print(f"db_path: {db_path.resolve()}")
        print(f"run_id: {run_id}")
        print(f"saturated_split_nodes_selected: {planned_calls}")

        if planned_calls == 0:
            print("No saturated split nodes to process.")
            return

        preview_limit = min(planned_calls, 10)
        for row in nodes[:preview_limit]:
            extra_radius = max(float(row["min_radius_m"]), float(row["radius_m"]) / 2.0)
            print(
                f"cell_id={row['id']} cell_key={row['cell_key']} center=({row['center_lat']:.6f},{row['center_lng']:.6f}) "
                f"parent_radius={row['radius_m']:.1f} extra_center_radius={extra_radius:.1f}"
            )
        if planned_calls > preview_limit:
            print(f"... ({planned_calls - preview_limit} more nodes)")

        if args.dry_run:
            print("No API calls made (--dry-run).")
            return

        if not api_key:
            raise SystemExit("Missing GOOGLE_PLACES_API_KEY environment variable.")

        seen = load_existing_place_ids(conn)
        total_inserted = 0
        total_duplicates = 0
        total_errors = 0
        total_http_200 = 0
        calls_made = 0

        for row in nodes:
            parent_cell_id = int(row["id"])
            parent_cell_key = str(row["cell_key"])
            center_lat = float(row["center_lat"])
            center_lng = float(row["center_lng"])
            query_radius_m = max(float(row["min_radius_m"]), float(row["radius_m"]) / 2.0)

            requested_at = utc_now_iso()
            calls_made += 1

            try:
                places, http_status = fetch_places(
                    api_key=api_key,
                    lat=center_lat,
                    lng=center_lng,
                    radius_m=query_radius_m,
                    timeout_sec=float(args.request_timeout_sec),
                )
                inserted, duplicates = insert_places(conn, places, seen)
                total_inserted += inserted
                total_duplicates += duplicates
                if http_status == 200:
                    total_http_200 += 1

                upsert_recheck_row(
                    conn,
                    run_id=run_id,
                    parent_cell_id=parent_cell_id,
                    parent_cell_key=parent_cell_key,
                    requested_at=requested_at,
                    responded_at=utc_now_iso(),
                    http_status=http_status,
                    query_radius_m=query_radius_m,
                    result_count=len(places),
                    inserted_count=inserted,
                    duplicate_count=duplicates,
                    error_message=None,
                )

                print(
                    f"[{calls_made}/{planned_calls}] OK cell_id={parent_cell_id} "
                    f"results={len(places)} inserted={inserted} dup={duplicates} radius={query_radius_m:.1f}"
                )

            except Exception as exc:
                total_errors += 1
                err = str(exc)
                upsert_recheck_row(
                    conn,
                    run_id=run_id,
                    parent_cell_id=parent_cell_id,
                    parent_cell_key=parent_cell_key,
                    requested_at=requested_at,
                    responded_at=utc_now_iso(),
                    http_status=getattr(getattr(exc, "response", None), "status_code", None),
                    query_radius_m=query_radius_m,
                    result_count=None,
                    inserted_count=None,
                    duplicate_count=None,
                    error_message=err,
                )
                print(f"[{calls_made}/{planned_calls}] ERROR cell_id={parent_cell_id} error={err}")

            if float(args.request_delay_sec) > 0:
                time.sleep(float(args.request_delay_sec))

        print("=== Saturated Recheck Summary ===")
        print(f"extra_calls_made: {calls_made}")
        print(f"http_200_calls: {total_http_200}")
        print(f"errors: {total_errors}")
        print(f"unique_places_inserted: {total_inserted}")
        print(f"duplicates_ignored: {total_duplicates}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
