import sqlite3
import random
import os
from pathlib import Path
from ..backend.database import get_db

# Paths

DB_PATH = "data/restaurants.db"
RANDOM_SEED = 42

# Cuisine weights (urban mix)
CUISINE_WEIGHTS = {
    "mexican": 0.15,
    "italian": 0.12,
    "american": 0.10,
    "chinese": 0.09,
    "japanese": 0.08,
    "thai": 0.07,
    "indian": 0.06,
    "french": 0.05,
    "mediterranean": 0.05,
    "korean": 0.04,
    "vietnamese": 0.04,
    "spanish": 0.03,
    "greek": 0.03,
    "peruvian": 0.02,
    "ethiopian": 0.02,
    "others": 0.05
}
def query_operational_restaurants(cursor):
    # Expand for weighted random choice
    cuisine_pool = []
    for cuisine, prob in CUISINE_WEIGHTS.items():
        cuisine_pool.extend([cuisine] * int(prob * 1000))  # higher precision

    # Fetch only operational places with id and price_level (as string)
    cursor.execute("""
        SELECT id, price_level 
        FROM restaurants 
        WHERE business_status = 'OPERATIONAL'
    """)

    operational_restaurants = cursor.fetchall()
    print(f"Found {len(operational_restaurants)} operational restaurants.")
    return operational_restaurants, cuisine_pool

def map_price_tier(price_str):
    """Map Google string enum to tier; return (tier, is_synthetic)"""
    if price_str is None:
        return None, True
    
    mapping = {
        "PRICE_LEVEL_INEXPENSIVE": 1,
        "PRICE_LEVEL_MODERATE": 2,
        "PRICE_LEVEL_EXPENSIVE": 3,
        "PRICE_LEVEL_VERY_EXPENSIVE": 3
    }
    tier = mapping.get(price_str, None)
    if tier is None:
        return None, True
    return tier, False

def generate_synthetic_attributes(operational_restaurants, cuisine_pool):
    synth_records = []

    for place_id, price_str in operational_restaurants:
        # Handle price
        if price_str is None:
            # Generate synthetic price tier
            tier = random.choices([1, 2, 3], weights=[0.4, 0.4, 0.2])[0]
            price_is_synth = True
        else:
            tier, price_is_synth = map_price_tier(price_str)
            if tier is None:  # fallback for unknown strings
                tier = random.choices([1, 2, 3], weights=[0.4, 0.4, 0.2])[0]
                price_is_synth = None

        # Assign cuisine
        cuisine = random.choice(cuisine_pool)

        # Generate base attributes
        has_outdoor = random.random() < 0.40
        is_vegan = random.random() < 0.20

        # Correlate with price if real
        if not price_is_synth:
            good_for_dates = random.random() < (0.30 if tier >= 2 else 0.10)
            has_cocktails = random.random() < (0.60 if tier >= 2 else 0.30)
        else:
            # Neutral prior
            good_for_dates = random.random() < 0.20
            has_cocktails = random.random() < 0.45

        # Anti-correlated: groups vs quiet
        if random.random() < 0.5:
            good_for_groups = True
            quiet_ambiance = random.random() < 0.20
        else:
            good_for_groups = False
            quiet_ambiance = random.random() < 0.60

        synth_records.append((
            place_id,
            cuisine,
            tier,
            price_is_synth,
            has_outdoor,
            is_vegan,
            good_for_dates,
            good_for_groups,
            quiet_ambiance,
            has_cocktails
        ))
    return synth_records

def main():
    # Set random seed for reproducibility
    random.seed(RANDOM_SEED)

    conn = get_db()
    cursor = conn.cursor()

    # Query operational restaurants
    operational_restaurants, cuisine_pool = query_operational_restaurants(cursor)

    # Generate synthetic tags
    synth_records = generate_synthetic_attributes(operational_restaurants, cuisine_pool)

    # Insert into synthetic_attributes table in db
    cursor.executemany("""
        INSERT OR REPLACE INTO synthetic_attributes 
        (place_id, cuisine, price_tier, price_is_synthetic,
        has_outdoor_seating, is_vegan_friendly, good_for_dates,
        good_for_groups, quiet_ambiance, has_cocktails)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, synth_records)

    conn.commit()
    print(f"Inserted {len(synth_records)} synthetic records.")
    conn.close()

if __name__ == "__main__":
    main()