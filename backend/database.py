# database.py
import sqlite3

DB_PATH = "./data/restaurants.db"  # relative to API_endpoints/

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO users (id) VALUES (1)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            deleted_at TEXT DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS list_restaurants (
            list_id INTEGER NOT NULL,
            restaurant_id INTEGER NOT NULL,
            PRIMARY KEY (list_id, restaurant_id),
            FOREIGN KEY (list_id) REFERENCES lists(id),
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER NOT NULL,
            restaurant_id INTEGER NOT NULL,
            list_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, restaurant_id, list_id),
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
            FOREIGN KEY (list_id) REFERENCES lists(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS synthetic_attributes (
            place_id TEXT PRIMARY KEY,
            cuisine TEXT,
            price_tier INTEGER CHECK(price_tier IN (1, 2, 3)),
            price_is_synthetic BOOLEAN,
            has_outdoor_seating BOOLEAN,
            is_vegan_friendly BOOLEAN,
            good_for_dates BOOLEAN,
            good_for_groups BOOLEAN,
            quiet_ambiance BOOLEAN,
            has_cocktails BOOLEAN,
            FOREIGN KEY(place_id) REFERENCES restaurants(place_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restaurant_features (
            place_id INTEGER PRIMARY KEY,
            cuisine TEXT,
            price_tier INTEGER CHECK(price_tier IN (1, 2, 3)),
            has_outdoor_seating BOOLEAN,
            is_vegan_friendly BOOLEAN,
            good_for_dates BOOLEAN,
            good_for_groups BOOLEAN,
            quiet_ambiance BOOLEAN,
            has_cocktails BOOLEAN,
            source TEXT DEFAULT 'real',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(place_id) REFERENCES restaurants(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS processed_ratings (
            user_id INTEGER NOT NULL,
            restaurant_id INTEGER NOT NULL,
            list_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, restaurant_id, list_id),
            FOREIGN KEY (user_id, restaurant_id, list_id) 
                REFERENCES ratings(user_id, restaurant_id, list_id)
        )
    """)    
    conn.commit()
    conn.close()

# For personal reference:
# python -m http.server 8080 - to serve frontend
# uvicorn API_endpoints.main:app --reload --port 8000 - to serve backend
# python -m data.ML_recs.train_model - to train model for very first time
# python -m data.generate --seed 42 --num-users 500 --sessions-per-user 15 --synthetic_ratings1.csv -- very first synthetic_ratings generations
# My target audience is people who want a way to keep accurate records of visited restaurants.
# and want easy recommendations.
# The main problem I'm addressing is Beli's degradation of rating relevance with respect to time and poor recommendations.
