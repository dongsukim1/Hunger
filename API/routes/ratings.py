# routes/ratings.py
from fastapi import APIRouter, HTTPException
import sqlite3
from ..database import get_db
from ..models import RatingCreate

router = APIRouter(tags=["ratings"])

@router.post("/rate", status_code=201)
def rate_restaurant(data: RatingCreate):
    if not (1 <= data.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1", (data.list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="List not found")
    cursor.execute("SELECT id FROM restaurants WHERE id = ?", (data.restaurant_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Restaurant not found")
    try:
        cursor.execute("INSERT INTO ratings (user_id, restaurant_id, list_id, rating) VALUES (?, ?, ?, ?)", (1, data.restaurant_id, data.list_id, data.rating))
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=409, detail="Rating already exists for this restaurant in this list")
    conn.commit()
    conn.close()
    return {"message": "Rating submitted"}