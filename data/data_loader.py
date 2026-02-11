from backend.database import get_db

def load_restaurants_from_db():
    """Reload restaurants with synthetic attributes from the database."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.id, r.name, s.cuisine, s.price_tier, 
            s.has_outdoor_seating, s.is_vegan_friendly, 
            s.good_for_dates, s.good_for_groups, 
            s.quiet_ambiance, s.has_cocktails
        FROM restaurants r
        JOIN synthetic_attributes s ON r.id = s.place_id
        WHERE r.business_status = 'OPERATIONAL'
    """)
    restaurants = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return restaurants