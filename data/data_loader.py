from backend.database import get_db

def load_restaurants_from_db(include_location: bool = False):
    """
    Load operational restaurants with canonical feature columns.
    Prefers `restaurant_features` (real tags) and falls back to
    `synthetic_attributes` for backward compatibility.
    """
    conn = get_db()
    cursor = conn.cursor()

    select_location = ", r.latitude, r.longitude" if include_location else ""
    cursor.execute(f"""
        SELECT
            r.id,
            r.name
            {select_location},
            COALESCE(rf.cuisine, s.cuisine) AS cuisine,
            COALESCE(rf.price_tier, s.price_tier) AS price_tier,
            COALESCE(rf.has_outdoor_seating, s.has_outdoor_seating) AS has_outdoor_seating,
            COALESCE(rf.is_vegan_friendly, s.is_vegan_friendly) AS is_vegan_friendly,
            COALESCE(rf.good_for_dates, s.good_for_dates) AS good_for_dates,
            COALESCE(rf.good_for_groups, s.good_for_groups) AS good_for_groups,
            COALESCE(rf.quiet_ambiance, s.quiet_ambiance) AS quiet_ambiance,
            COALESCE(rf.has_cocktails, s.has_cocktails) AS has_cocktails
        FROM restaurants r
        LEFT JOIN restaurant_features rf ON r.id = rf.place_id
        LEFT JOIN synthetic_attributes s ON r.id = s.place_id
        WHERE
            r.business_status = 'OPERATIONAL'
            AND COALESCE(rf.cuisine, s.cuisine) IS NOT NULL
            AND COALESCE(rf.price_tier, s.price_tier) IS NOT NULL
    """)
    restaurants = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return restaurants
