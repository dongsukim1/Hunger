import argparse
from backend.database import get_db


BOOLEAN_FIELDS = [
    "has_outdoor_seating",
    "is_vegan_friendly",
    "good_for_dates",
    "good_for_groups",
    "quiet_ambiance",
    "has_cocktails",
]


def map_price_tier(value):
    """
    Normalize either Google enum strings or numeric values to tier 1..3.
    """
    if value is None:
        return None

    if isinstance(value, int):
        if value in (0, 1):
            return 1
        if value == 2:
            return 2
        if value in (3, 4):
            return 3
        return None

    text = str(value).strip().upper()
    enum_map = {
        "PRICE_LEVEL_FREE": 1,
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 3,
    }
    if text in enum_map:
        return enum_map[text]

    if text.isdigit():
        as_int = int(text)
        return map_price_tier(as_int)
    return None


def _to_bool_or_none(value):
    if value is None:
        return None
    return bool(value)


def build_feature_record(row):
    place_id = row["id"]
    synth_cuisine = row["s_cuisine"]
    synth_price_tier = row["s_price_tier"]
    rest_price_level = row["r_price_level"]

    cuisine = synth_cuisine
    price_tier = synth_price_tier if synth_price_tier is not None else map_price_tier(rest_price_level)

    out = {
        "place_id": place_id,
        "cuisine": cuisine,
        "price_tier": price_tier,
        "source": "synthetic_backfill",
    }
    for field in BOOLEAN_FIELDS:
        out[field] = _to_bool_or_none(row[f"s_{field}"])
    return out


def backfill(limit=None, dry_run=False):
    conn = get_db()
    cursor = conn.cursor()

    query = """
        SELECT
            r.id,
            r.price_level AS r_price_level,
            s.cuisine AS s_cuisine,
            s.price_tier AS s_price_tier,
            s.has_outdoor_seating AS s_has_outdoor_seating,
            s.is_vegan_friendly AS s_is_vegan_friendly,
            s.good_for_dates AS s_good_for_dates,
            s.good_for_groups AS s_good_for_groups,
            s.quiet_ambiance AS s_quiet_ambiance,
            s.has_cocktails AS s_has_cocktails
        FROM restaurants r
        LEFT JOIN synthetic_attributes s ON r.id = s.place_id
        WHERE r.business_status = 'OPERATIONAL'
    """
    if limit is not None and limit > 0:
        query += f" LIMIT {int(limit)}"
    cursor.execute(query)
    rows = cursor.fetchall()

    records = [build_feature_record(row) for row in rows]
    with_payload = [rec for rec in records if rec["cuisine"] is not None and rec["price_tier"] is not None]

    if dry_run:
        print(f"[dry-run] operational rows scanned: {len(rows)}")
        print(f"[dry-run] backfill-ready records: {len(with_payload)}")
        conn.close()
        return

    payload = []
    for rec in with_payload:
        payload.append(
            (
                rec["place_id"],
                rec["cuisine"],
                rec["price_tier"],
                rec["has_outdoor_seating"],
                rec["is_vegan_friendly"],
                rec["good_for_dates"],
                rec["good_for_groups"],
                rec["quiet_ambiance"],
                rec["has_cocktails"],
                rec["source"],
            )
        )

    cursor.executemany(
        """
        INSERT INTO restaurant_features (
            place_id, cuisine, price_tier,
            has_outdoor_seating, is_vegan_friendly, good_for_dates,
            good_for_groups, quiet_ambiance, has_cocktails, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(place_id) DO UPDATE SET
            cuisine = COALESCE(restaurant_features.cuisine, excluded.cuisine),
            price_tier = COALESCE(restaurant_features.price_tier, excluded.price_tier),
            has_outdoor_seating = COALESCE(restaurant_features.has_outdoor_seating, excluded.has_outdoor_seating),
            is_vegan_friendly = COALESCE(restaurant_features.is_vegan_friendly, excluded.is_vegan_friendly),
            good_for_dates = COALESCE(restaurant_features.good_for_dates, excluded.good_for_dates),
            good_for_groups = COALESCE(restaurant_features.good_for_groups, excluded.good_for_groups),
            quiet_ambiance = COALESCE(restaurant_features.quiet_ambiance, excluded.quiet_ambiance),
            has_cocktails = COALESCE(restaurant_features.has_cocktails, excluded.has_cocktails),
            source = CASE
                WHEN restaurant_features.source IS NULL OR restaurant_features.source = '' THEN excluded.source
                ELSE restaurant_features.source
            END,
            updated_at = CURRENT_TIMESTAMP
        """,
        payload,
    )
    conn.commit()

    cursor.execute("SELECT COUNT(*) AS n FROM restaurant_features")
    total = cursor.fetchone()["n"]
    print(f"Operational rows scanned: {len(rows)}")
    print(f"Backfill-ready records: {len(with_payload)}")
    print(f"Rows upserted into restaurant_features: {len(payload)}")
    print(f"Current restaurant_features row count: {total}")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill canonical restaurant_features table.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit for testing")
    parser.add_argument("--dry-run", action="store_true", help="Analyze only; do not write")
    args = parser.parse_args()
    backfill(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
