import os
from backend.database import get_db

FEATURE_MODE_ENV = "HUNGER_FEATURE_MODE"
MODE_CANONICAL_FALLBACK = "canonical+fallback"
MODE_CANONICAL_ONLY = "canonical-only"


def _resolve_feature_mode(feature_mode):
    mode = (feature_mode or os.getenv(FEATURE_MODE_ENV, MODE_CANONICAL_FALLBACK)).strip().lower()
    if mode in {"canonical_only", "canonical-only", "canonical"}:
        return MODE_CANONICAL_ONLY
    # Default preserves existing behavior.
    return MODE_CANONICAL_FALLBACK


def load_restaurants_from_db(include_location: bool = False, feature_mode: str | None = None):
    """
    Load operational restaurants with canonical feature columns.
    Feature modes:
      - canonical+fallback (default): prefer canonical `restaurant_features`,
        fallback to `synthetic_attributes`.
      - canonical-only: use only canonical `restaurant_features`.
    """
    conn = get_db()
    cursor = conn.cursor()
    mode = _resolve_feature_mode(feature_mode)

    select_location = ", r.latitude, r.longitude" if include_location else ""
    if mode == MODE_CANONICAL_ONLY:
        cursor.execute(
            f"""
            SELECT
                r.id,
                r.name
                {select_location},
                rf.cuisine AS cuisine,
                rf.price_tier AS price_tier,
                rf.has_outdoor_seating AS has_outdoor_seating,
                rf.is_vegan_friendly AS is_vegan_friendly,
                rf.good_for_dates AS good_for_dates,
                rf.good_for_groups AS good_for_groups,
                rf.quiet_ambiance AS quiet_ambiance,
                rf.has_cocktails AS has_cocktails
            FROM restaurants r
            JOIN restaurant_features rf ON r.id = rf.place_id
            WHERE
                r.business_status = 'OPERATIONAL'
                AND rf.cuisine IS NOT NULL
                AND rf.price_tier IS NOT NULL
            """
        )
    else:
        cursor.execute(
            f"""
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
            """
        )
    restaurants = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return restaurants
