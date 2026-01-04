# routes/restaurants.py
from fastapi import APIRouter, HTTPException
from typing import List
from ..database import get_db
from ..models import RestaurantIngest

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

@router.post("/ingest", status_code=201)
def ingest_restaurants(restaurants: List[RestaurantIngest]):
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

@router.get("/search")
def search_restaurants(q: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM restaurants WHERE name LIKE ? ORDER BY name LIMIT 10", (f"%{q}%",))
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results