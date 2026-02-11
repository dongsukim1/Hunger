from backend.database import get_db


FIELDS = [
    "cuisine",
    "price_tier",
    "has_outdoor_seating",
    "is_vegan_friendly",
    "good_for_dates",
    "good_for_groups",
    "quiet_ambiance",
    "has_cocktails",
]


def _pct(num, den):
    if not den:
        return 0.0
    return 100.0 * float(num) / float(den)


def validate():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS n FROM restaurants WHERE business_status = 'OPERATIONAL'")
    operational_total = cur.fetchone()["n"]

    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM restaurants r
        JOIN restaurant_features rf ON r.id = rf.place_id
        WHERE r.business_status = 'OPERATIONAL'
        """
    )
    with_canonical = cur.fetchone()["n"]

    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM restaurants r
        LEFT JOIN restaurant_features rf ON r.id = rf.place_id
        WHERE r.business_status = 'OPERATIONAL' AND rf.place_id IS NULL
        """
    )
    missing_rows = cur.fetchone()["n"]

    print("Canonical restaurant_features validation")
    print(f"Operational restaurants: {operational_total}")
    print(f"Operational rows with canonical record: {with_canonical} ({_pct(with_canonical, operational_total):.1f}%)")
    print(f"Operational rows missing canonical record: {missing_rows} ({_pct(missing_rows, operational_total):.1f}%)")

    for field in FIELDS:
        cur.execute(
            f"""
            SELECT
                SUM(CASE WHEN rf.{field} IS NULL THEN 1 ELSE 0 END) AS null_count,
                COUNT(*) AS total
            FROM restaurants r
            LEFT JOIN restaurant_features rf ON r.id = rf.place_id
            WHERE r.business_status = 'OPERATIONAL'
            """
        )
        row = cur.fetchone()
        null_count = row["null_count"] or 0
        total = row["total"] or 0
        print(f"{field}: null_or_missing={null_count} ({_pct(null_count, total):.1f}%)")

    # Key readiness signal for canonical-only cutover.
    cur.execute(
        """
        SELECT COUNT(*) AS n
        FROM restaurants r
        LEFT JOIN restaurant_features rf ON r.id = rf.place_id
        WHERE
            r.business_status = 'OPERATIONAL'
            AND (rf.cuisine IS NULL OR rf.price_tier IS NULL)
        """
    )
    missing_required = cur.fetchone()["n"]
    print(f"Missing required canonical fields (cuisine or price_tier): {missing_required}")

    conn.close()


if __name__ == "__main__":
    validate()
