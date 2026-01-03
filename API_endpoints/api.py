from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import sqlite3
import os

app = FastAPI(title="Contextual Restaurant Recommender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8080"],  # your frontend origin
    allow_credentials=True,
    allow_methods=["*"],  # allows POST, GET, OPTIONS, etc.
    allow_headers=["*"],
)

DB_PATH = "../data/restaurants.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # enables dict-like access
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Single user (user_id = 1)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO users (id) VALUES (1)")

    # Lists (contexts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Many-to-many: list ↔ restaurant
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS list_restaurants (
            list_id INTEGER NOT NULL,
            restaurant_id INTEGER NOT NULL,
            PRIMARY KEY (list_id, restaurant_id),
            FOREIGN KEY (list_id) REFERENCES lists(id),
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
        )
    """)

    # Contextual ratings
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER NOT NULL,
            restaurant_id INTEGER NOT NULL,
            list_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, restaurant_id, list_id),
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
            FOREIGN KEY (list_id) REFERENCES lists(id)
        )
    """)

    conn.commit()
    conn.close()

# Initialize DB on startup
init_db()


# --- Models ---
class RestaurantIngest(BaseModel):
    google_place_id: str
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    price_level: Optional[int] = None
    business_status: Optional[str] = "OPERATIONAL"

class ListCreate(BaseModel):
    name: str

class AddRestaurantToList(BaseModel):
    restaurant_id: int

class RatingCreate(BaseModel):
    restaurant_id: int
    list_id: int
    rating: int

# --- Endpoints ---

@app.post("/ingest_restaurants", status_code=status.HTTP_201_CREATED)
def ingest_restaurants(restaurants: List[RestaurantIngest]):
    """One-time bulk ingest (e.g., from backup or alternative source)."""
    conn = get_db()
    cursor = conn.cursor()
    inserted = 0
    for r in restaurants:
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO restaurants (
                    google_place_id, name, latitude, longitude, address, price_level, business_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                r.google_place_id, r.name, r.latitude, r.longitude,
                r.address, r.price_level, r.business_status
            ))
            if cursor.rowcount > 0:
                inserted += 1
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Insert failed: {str(e)}")
    conn.commit()
    conn.close()
    return {"inserted": inserted}

@app.post("/lists", status_code=status.HTTP_201_CREATED)
def create_list(data: ListCreate):
    """Create a new context (list)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO lists (user_id, name) VALUES (?, ?)",
        (1, data.name)  # user_id = 1
    )
    list_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": list_id, "name": data.name}

@app.post("/lists/{list_id}/add_restaurant", status_code=status.HTTP_201_CREATED)
def add_restaurant_to_list(list_id: int, data: AddRestaurantToList):
    """Add a restaurant to a list."""
    conn = get_db()
    cursor = conn.cursor()

    # Verify list exists and belongs to user
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1", (list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="List not found")

    # Verify restaurant exists
    cursor.execute("SELECT id FROM restaurants WHERE id = ?", (data.restaurant_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Add to list_restaurants
    cursor.execute("""
        INSERT OR IGNORE INTO list_restaurants (list_id, restaurant_id)
        VALUES (?, ?)
    """, (list_id, data.restaurant_id))

    conn.commit()
    conn.close()
    return {"message": "Restaurant added to list"}

@app.post("/rate", status_code=status.HTTP_201_CREATED)
def rate_restaurant(data: RatingCreate):
    """Submit a contextual rating."""
    if not (1 <= data.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    conn = get_db()
    cursor = conn.cursor()

    # Verify list exists (and belongs to user)
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1", (data.list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="List not found")

    # Verify restaurant exists
    cursor.execute("SELECT id FROM restaurants WHERE id = ?", (data.restaurant_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Restaurant not found")

    # Insert rating
    try:
        cursor.execute("""
            INSERT INTO ratings (user_id, restaurant_id, list_id, rating)
            VALUES (?, ?, ?, ?)
        """, (1, data.restaurant_id, data.list_id, data.rating))
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="Rating already exists for this restaurant in this list")

    conn.commit()
    conn.close()
    return {"message": "Rating submitted"}

@app.get("/lists")
def get_lists():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM lists WHERE user_id = 1")
    lists = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return lists

@app.get("/restaurants/search")
def search_restaurants(q: str):
    conn = get_db()
    cursor = conn.cursor()
    # Simple case-insensitive partial match
    cursor.execute("""
        SELECT id, name FROM restaurants 
        WHERE name LIKE ? 
        ORDER BY name
        LIMIT 10
    """, (f"%{q}%",))
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results