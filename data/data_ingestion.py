import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

HARD_MAX_CALLS = 4000
SATURATION_THRESHOLD = 18
GOOGLE_API_URL = "https://places.googleapis.com/v1/places:searchNearby"
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.location,"
    "places.priceLevel,"
    "places.businessStatus,"
    "places.formattedAddress"
)

LOGGER = logging.getLogger("data_ingestion_trial")


@dataclass
class RegionConfig:
    name: str
    bbox: Tuple[float, float, float, float]
    initial_radius_m: float
    min_radius_m: float
    overlap_step_ratio: float


@dataclass
class Cell:
    run_id: int
    region_name: str
    cell_key: str
    parent_cell_key: Optional[str]
    depth: int
    center_lat: float
    center_lng: float
    radius_m: float
    min_radius_m: float



def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")



def resolve_default_config_path() -> Path:
    return Path(__file__).resolve().parent / "ingestion_config.yaml"



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trial-only Google Places ingestion pipeline")
    parser.add_argument(
        "--db-path",
        default=str(Path("data") / "restaurants_trial.db"),
        help="Target SQLite DB path for trial ingestion (default: data/restaurants_trial.db)",
    )
    parser.add_argument(
        "--allow-prod-db",
        action="store_true",
        help="Allow writes to data/restaurants.db (blocked by default)",
    )
    parser.add_argument(
        "--config",
        default=str(resolve_default_config_path()),
        help="Path to ingestion config file (YAML or JSON)",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help=f"Requested API call cap. Effective cap is min(value, {HARD_MAX_CALLS}).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume the latest unfinished trial ingestion run from metadata tables.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned regions/cells and call estimates without hitting the API.",
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
        help="Delay between API requests.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()



def safe_load_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        LOGGER.warning("Config not found at %s, using built-in default region.", config_path)
        return {
            "regions": [
                {
                    "name": "mission_sf",
                    "bbox": [37.74802895624222, -122.42248265700066, 37.769249996806195, -122.40801467343661],
                    "initial_radius_m": 100,
                    "min_radius_m": 35,
                    "overlap_step_ratio": 0.7,
                }
            ]
        }

    raw = config_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Config is not valid JSON and PyYAML is not installed. "
                "Install pyyaml or provide JSON-formatted config."
            ) from exc
        data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError("Config root must be an object with a 'regions' key.")
    return data



def parse_regions(config: Dict[str, Any]) -> List[RegionConfig]:
    regions_raw = config.get("regions")
    if not isinstance(regions_raw, list) or not regions_raw:
        raise ValueError("Config must define non-empty 'regions' list.")

    regions: List[RegionConfig] = []
    for i, item in enumerate(regions_raw):
        if not isinstance(item, dict):
            raise ValueError(f"Region #{i + 1} must be an object.")

        name = str(item.get("name") or f"region_{i + 1}")
        bbox = item.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            raise ValueError(f"Region '{name}' must provide bbox=[sw_lat, sw_lng, ne_lat, ne_lng].")

        sw_lat, sw_lng, ne_lat, ne_lng = [float(v) for v in bbox]
        if sw_lat >= ne_lat or sw_lng >= ne_lng:
            raise ValueError(f"Region '{name}' has invalid bbox ordering.")

        initial_radius_m = float(item.get("initial_radius_m", 100))
        min_radius_m = float(item.get("min_radius_m", 35))
        overlap_step_ratio = float(item.get("overlap_step_ratio", 0.7))

        if initial_radius_m <= 0 or min_radius_m <= 0:
            raise ValueError(f"Region '{name}' radii must be > 0.")
        if min_radius_m > initial_radius_m:
            raise ValueError(f"Region '{name}' min_radius_m cannot exceed initial_radius_m.")
        if overlap_step_ratio <= 0 or overlap_step_ratio > 1.5:
            raise ValueError(f"Region '{name}' overlap_step_ratio must be in (0, 1.5].")

        regions.append(
            RegionConfig(
                name=name,
                bbox=(sw_lat, sw_lng, ne_lat, ne_lng),
                initial_radius_m=initial_radius_m,
                min_radius_m=min_radius_m,
                overlap_step_ratio=overlap_step_ratio,
            )
        )

    return regions



def meters_to_lat_degrees(meters: float) -> float:
    return meters / 111320.0



def meters_to_lng_degrees(meters: float, lat: float) -> float:
    denom = 111320.0 * math.cos(math.radians(lat))
    if abs(denom) < 1e-9:
        return 0.0
    return meters / denom



def generate_initial_cells(region: RegionConfig, run_id: int) -> List[Cell]:
    sw_lat, sw_lng, ne_lat, ne_lng = region.bbox
    step_m = max(1.0, region.initial_radius_m * region.overlap_step_ratio)

    lat_step = meters_to_lat_degrees(step_m)
    cells: List[Cell] = []

    lat = sw_lat
    row = 0
    while lat <= ne_lat + 1e-9:
        lng_step = meters_to_lng_degrees(step_m, lat)
        if lng_step <= 0:
            break

        lng = sw_lng
        col = 0
        while lng <= ne_lng + 1e-9:
            key = f"{region.name}:d0:r{row}:c{col}"
            cells.append(
                Cell(
                    run_id=run_id,
                    region_name=region.name,
                    cell_key=key,
                    parent_cell_key=None,
                    depth=0,
                    center_lat=lat,
                    center_lng=lng,
                    radius_m=region.initial_radius_m,
                    min_radius_m=region.min_radius_m,
                )
            )
            lng += lng_step
            col += 1

        lat += lat_step
        row += 1

    return cells



def split_cell(cell: Cell) -> List[Cell]:
    next_radius = cell.radius_m / 2.0
    if next_radius < cell.min_radius_m:
        return []

    offset_m = next_radius * 0.8
    lat_off = meters_to_lat_degrees(offset_m)
    lng_off = meters_to_lng_degrees(offset_m, cell.center_lat)

    offsets = [
        (lat_off, lng_off),
        (lat_off, -lng_off),
        (-lat_off, lng_off),
        (-lat_off, -lng_off),
    ]

    children: List[Cell] = []
    for idx, (dlat, dlng) in enumerate(offsets):
        children.append(
            Cell(
                run_id=cell.run_id,
                region_name=cell.region_name,
                cell_key=f"{cell.cell_key}.{idx}",
                parent_cell_key=cell.cell_key,
                depth=cell.depth + 1,
                center_lat=cell.center_lat + dlat,
                center_lng=cell.center_lng + dlng,
                radius_m=next_radius,
                min_radius_m=cell.min_radius_m,
            )
        )
    return children



def estimate_calls_for_radius(radius_m: float, min_radius_m: float) -> int:
    if radius_m / 2.0 < min_radius_m:
        return 1
    return 1 + 4 * estimate_calls_for_radius(radius_m / 2.0, min_radius_m)



def ensure_db_guard(db_path: Path, allow_prod_db: bool) -> None:
    prod_db = (Path(__file__).resolve().parent / "restaurants.db").resolve()
    target = db_path.resolve()
    if target == prod_db and not allow_prod_db:
        raise SystemExit(
            "Refusing to write to production DB data/restaurants.db. "
            "Pass --allow-prod-db only if this is intentional."
        )



def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn



def create_tables(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY,
            google_place_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            address TEXT,
            price_level INTEGER,
            business_status TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_place_id ON restaurants(google_place_id)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL,
            db_path TEXT NOT NULL,
            config_path TEXT,
            max_calls INTEGER NOT NULL,
            calls_used INTEGER NOT NULL DEFAULT 0,
            allow_prod_db INTEGER NOT NULL DEFAULT 0,
            resume_from_run_id INTEGER,
            error_message TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_cells (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            region_name TEXT NOT NULL,
            cell_key TEXT NOT NULL,
            parent_cell_key TEXT,
            depth INTEGER NOT NULL,
            center_lat REAL NOT NULL,
            center_lng REAL NOT NULL,
            radius_m REAL NOT NULL,
            min_radius_m REAL NOT NULL,
            status TEXT NOT NULL,
            result_count INTEGER,
            inserted_count INTEGER,
            duplicate_count INTEGER,
            is_saturated INTEGER,
            error_message TEXT,
            scheduled_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            UNIQUE(run_id, cell_key),
            FOREIGN KEY(run_id) REFERENCES ingestion_runs(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            cell_id INTEGER,
            requested_at TEXT NOT NULL,
            responded_at TEXT,
            duration_ms INTEGER,
            api_call_number INTEGER NOT NULL,
            http_status INTEGER,
            result_count INTEGER,
            is_saturated INTEGER,
            error_message TEXT,
            FOREIGN KEY(run_id) REFERENCES ingestion_runs(id),
            FOREIGN KEY(cell_id) REFERENCES ingestion_cells(id)
        )
        """
    )

    cur.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_cells_run_status ON ingestion_cells(run_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_queries_run ON ingestion_queries(run_id)")
    conn.commit()



def insert_cells(conn: sqlite3.Connection, cells: Iterable[Cell], status: str = "pending") -> int:
    now = utc_now_iso()
    payload = [
        (
            c.run_id,
            c.region_name,
            c.cell_key,
            c.parent_cell_key,
            c.depth,
            c.center_lat,
            c.center_lng,
            c.radius_m,
            c.min_radius_m,
            status,
            now,
        )
        for c in cells
    ]
    if not payload:
        return 0

    cur = conn.cursor()
    cur.executemany(
        """
        INSERT OR IGNORE INTO ingestion_cells (
            run_id, region_name, cell_key, parent_cell_key, depth,
            center_lat, center_lng, radius_m, min_radius_m, status, scheduled_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        payload,
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None else 0



def get_latest_resumable_run(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM ingestion_runs
        WHERE status IN ('running', 'stopped', 'failed')
        ORDER BY id DESC
        LIMIT 1
        """
    )
    return cur.fetchone()



def create_run(
    conn: sqlite3.Connection,
    db_path: Path,
    config_path: Path,
    max_calls: int,
    allow_prod_db: bool,
    resume_from_run_id: Optional[int],
) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ingestion_runs (
            started_at, status, db_path, config_path, max_calls, calls_used, allow_prod_db, resume_from_run_id
        ) VALUES (?, 'running', ?, ?, ?, 0, ?, ?)
        """,
        (
            utc_now_iso(),
            str(db_path),
            str(config_path),
            max_calls,
            1 if allow_prod_db else 0,
            resume_from_run_id,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)



def mark_run_finished(conn: sqlite3.Connection, run_id: int, status: str, error_message: Optional[str] = None) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE ingestion_runs
        SET status = ?, finished_at = ?, error_message = ?
        WHERE id = ?
        """,
        (status, utc_now_iso(), error_message, run_id),
    )
    conn.commit()



def update_run_calls(conn: sqlite3.Connection, run_id: int, calls_used: int) -> None:
    cur = conn.cursor()
    cur.execute("UPDATE ingestion_runs SET calls_used = ? WHERE id = ?", (calls_used, run_id))
    conn.commit()



def claim_next_pending_cell(conn: sqlite3.Connection, run_id: int) -> Optional[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM ingestion_cells
        WHERE run_id = ? AND status = 'pending'
        ORDER BY id
        LIMIT 1
        """,
        (run_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None

    cur.execute(
        """
        UPDATE ingestion_cells
        SET status = 'processing', started_at = ?, error_message = NULL
        WHERE id = ?
        """,
        (utc_now_iso(), int(row["id"])),
    )
    conn.commit()
    cur.execute("SELECT * FROM ingestion_cells WHERE id = ?", (int(row["id"]),))
    return cur.fetchone()



def requeue_processing_cells(conn: sqlite3.Connection, run_id: int) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE ingestion_cells
        SET status = 'pending', started_at = NULL
        WHERE run_id = ? AND status = 'processing'
        """,
        (run_id,),
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None else 0



def fetch_places_nearby(api_key: str, lat: float, lng: float, radius_m: float, timeout_sec: float) -> Tuple[List[Dict[str, Any]], int]:
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



def write_query_row(
    conn: sqlite3.Connection,
    run_id: int,
    cell_id: int,
    requested_at: str,
    responded_at: Optional[str],
    duration_ms: Optional[int],
    api_call_number: int,
    http_status: Optional[int],
    result_count: Optional[int],
    is_saturated: Optional[bool],
    error_message: Optional[str],
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO ingestion_queries (
            run_id, cell_id, requested_at, responded_at, duration_ms, api_call_number,
            http_status, result_count, is_saturated, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            cell_id,
            requested_at,
            responded_at,
            duration_ms,
            api_call_number,
            http_status,
            result_count,
            1 if is_saturated else 0 if is_saturated is not None else None,
            error_message,
        ),
    )
    conn.commit()



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



def load_all_existing_place_ids(conn: sqlite3.Connection) -> set[str]:
    cur = conn.cursor()
    cur.execute("SELECT google_place_id FROM restaurants")
    return {str(row[0]) for row in cur.fetchall()}



def insert_places(
    conn: sqlite3.Connection,
    places: List[Dict[str, Any]],
    seen_place_ids: set[str],
) -> Tuple[int, int]:
    inserted = 0
    duplicates = 0
    cur = conn.cursor()

    for raw_place in places:
        row = normalize_place(raw_place)
        if row is None:
            continue

        place_id = row[0]
        if place_id in seen_place_ids:
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

        seen_place_ids.add(place_id)
        if cur.rowcount and cur.rowcount > 0:
            inserted += 1
        else:
            duplicates += 1

    conn.commit()
    return inserted, duplicates



def update_cell_success(
    conn: sqlite3.Connection,
    cell_id: int,
    status: str,
    result_count: int,
    inserted_count: int,
    duplicate_count: int,
    is_saturated: bool,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE ingestion_cells
        SET status = ?, result_count = ?, inserted_count = ?, duplicate_count = ?,
            is_saturated = ?, finished_at = ?, error_message = NULL
        WHERE id = ?
        """,
        (
            status,
            result_count,
            inserted_count,
            duplicate_count,
            1 if is_saturated else 0,
            utc_now_iso(),
            cell_id,
        ),
    )
    conn.commit()



def update_cell_error(conn: sqlite3.Connection, cell_id: int, error_message: str) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE ingestion_cells
        SET status = 'error', error_message = ?, finished_at = ?
        WHERE id = ?
        """,
        (error_message[:1000], utc_now_iso(), cell_id),
    )
    conn.commit()



def print_dry_run(regions: List[RegionConfig], effective_max_calls: int) -> None:
    total_initial = 0
    worst_case = 0

    print("=== Dry Run Plan ===")
    for region in regions:
        cells = generate_initial_cells(region, run_id=0)
        initial = len(cells)
        per_cell_worst = estimate_calls_for_radius(region.initial_radius_m, region.min_radius_m)
        region_worst = initial * per_cell_worst

        total_initial += initial
        worst_case += region_worst

        print(
            f"Region={region.name} bbox={region.bbox} initial_radius_m={region.initial_radius_m} "
            f"min_radius_m={region.min_radius_m} overlap_step_ratio={region.overlap_step_ratio} "
            f"initial_cells={initial} worst_case_calls={region_worst}"
        )

    print(f"Total initial cells: {total_initial}")
    print(f"Estimated calls (initial only): {total_initial}")
    print(f"Estimated calls (worst-case adaptive): {worst_case}")
    print(f"Effective hard cap: {effective_max_calls}")
    print("No API calls made (--dry-run).")



def run_ingestion(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_db_guard(db_path, args.allow_prod_db)

    config_path = Path(args.config).expanduser()
    config = safe_load_config(config_path)
    regions = parse_regions(config)

    effective_max_calls = min(args.max_calls, HARD_MAX_CALLS) if args.max_calls is not None else HARD_MAX_CALLS
    if effective_max_calls <= 0:
        raise SystemExit("--max-calls must be > 0")

    if args.dry_run:
        print_dry_run(regions, effective_max_calls)
        return 0

    api_key = os.getenv("GOOGLE_PLACES_API_KEY")
    if not api_key:
        raise SystemExit("Missing GOOGLE_PLACES_API_KEY environment variable.")

    conn = open_db(db_path)
    create_tables(conn)

    run_id: Optional[int] = None
    calls_used = 0

    try:
        if args.resume:
            resumable = get_latest_resumable_run(conn)
            if resumable is not None:
                run_id = int(resumable["id"])
                calls_used = int(resumable["calls_used"] or 0)
                requeued = requeue_processing_cells(conn, run_id)
                LOGGER.info("Resuming run_id=%s (requeued %s processing cells)", run_id, requeued)
                cur = conn.cursor()
                cur.execute("UPDATE ingestion_runs SET status = 'running', max_calls = ? WHERE id = ?", (effective_max_calls, run_id))
                conn.commit()

        if run_id is None:
            run_id = create_run(
                conn=conn,
                db_path=db_path.resolve(),
                config_path=config_path.resolve(),
                max_calls=effective_max_calls,
                allow_prod_db=args.allow_prod_db,
                resume_from_run_id=None,
            )
            all_initial_cells: List[Cell] = []
            for region in regions:
                all_initial_cells.extend(generate_initial_cells(region, run_id=run_id))
            inserted_cells = insert_cells(conn, all_initial_cells, status="pending")
            LOGGER.info("Created new run_id=%s with %s initial cells", run_id, inserted_cells)

        seen_place_ids = load_all_existing_place_ids(conn)

        total_inserted = 0
        total_duplicates = 0
        saturated_cells_processed = 0

        while True:
            if calls_used >= effective_max_calls:
                LOGGER.warning("Call cap reached (%s). Stopping run.", effective_max_calls)
                mark_run_finished(conn, run_id, status="stopped")
                break

            row = claim_next_pending_cell(conn, run_id)
            if row is None:
                mark_run_finished(conn, run_id, status="completed")
                break

            cell_id = int(row["id"])
            cell = Cell(
                run_id=run_id,
                region_name=str(row["region_name"]),
                cell_key=str(row["cell_key"]),
                parent_cell_key=row["parent_cell_key"],
                depth=int(row["depth"]),
                center_lat=float(row["center_lat"]),
                center_lng=float(row["center_lng"]),
                radius_m=float(row["radius_m"]),
                min_radius_m=float(row["min_radius_m"]),
            )

            requested_at = utc_now_iso()
            started = time.perf_counter()
            calls_used += 1
            update_run_calls(conn, run_id, calls_used)

            try:
                places, status_code = fetch_places_nearby(
                    api_key=api_key,
                    lat=cell.center_lat,
                    lng=cell.center_lng,
                    radius_m=cell.radius_m,
                    timeout_sec=float(args.request_timeout_sec),
                )

                duration_ms = int((time.perf_counter() - started) * 1000)
                is_saturated = len(places) >= SATURATION_THRESHOLD
                inserted_count, duplicate_count = insert_places(conn, places, seen_place_ids)

                total_inserted += inserted_count
                total_duplicates += duplicate_count
                if is_saturated:
                    saturated_cells_processed += 1

                children = split_cell(cell) if is_saturated else []
                if children:
                    insert_cells(conn, children, status="pending")
                    cell_status = "split"
                else:
                    cell_status = "done"

                update_cell_success(
                    conn=conn,
                    cell_id=cell_id,
                    status=cell_status,
                    result_count=len(places),
                    inserted_count=inserted_count,
                    duplicate_count=duplicate_count,
                    is_saturated=is_saturated,
                )

                write_query_row(
                    conn=conn,
                    run_id=run_id,
                    cell_id=cell_id,
                    requested_at=requested_at,
                    responded_at=utc_now_iso(),
                    duration_ms=duration_ms,
                    api_call_number=calls_used,
                    http_status=status_code,
                    result_count=len(places),
                    is_saturated=is_saturated,
                    error_message=None,
                )

                LOGGER.info(
                    "run=%s call=%s cell=%s status=%s results=%s inserted=%s dup=%s radius=%.1f",
                    run_id,
                    calls_used,
                    cell.cell_key,
                    cell_status,
                    len(places),
                    inserted_count,
                    duplicate_count,
                    cell.radius_m,
                )

            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                err = str(exc)
                LOGGER.error("Cell failed run=%s cell=%s error=%s", run_id, cell.cell_key, err)

                update_cell_error(conn, cell_id=cell_id, error_message=err)
                write_query_row(
                    conn=conn,
                    run_id=run_id,
                    cell_id=cell_id,
                    requested_at=requested_at,
                    responded_at=utc_now_iso(),
                    duration_ms=duration_ms,
                    api_call_number=calls_used,
                    http_status=getattr(getattr(exc, "response", None), "status_code", None),
                    result_count=None,
                    is_saturated=None,
                    error_message=err,
                )

            if float(args.request_delay_sec) > 0:
                time.sleep(float(args.request_delay_sec))

        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*)
            FROM ingestion_cells
            WHERE run_id = ? AND is_saturated = 1
            """,
            (run_id,),
        )
        saturated_total = int(cur.fetchone()[0])

        places_per_100_calls = (total_inserted * 100.0 / calls_used) if calls_used > 0 else 0.0

        print("=== Trial Ingestion Summary ===")
        print(f"run_id: {run_id}")
        print(f"db_path: {db_path.resolve()}")
        print(f"total_calls_used: {calls_used}")
        print(f"unique_places_inserted: {total_inserted}")
        print(f"duplicates_ignored: {total_duplicates}")
        print(f"saturated_cells_processed: {saturated_total if saturated_total >= saturated_cells_processed else saturated_cells_processed}")
        print(f"new_unique_places_per_100_calls: {places_per_100_calls:.2f}")

        return 0

    except Exception as exc:
        if run_id is not None:
            mark_run_finished(conn, run_id, status="failed", error_message=str(exc))
        raise
    finally:
        conn.close()



def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)
    exit_code = run_ingestion(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
