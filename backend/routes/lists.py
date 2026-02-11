# routes/lists.py
from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone, timedelta
from typing import List
from ..database import get_db
from ..models import ListCreate, AddRestaurantToList

router = APIRouter(prefix="/lists", tags=["lists"])

@router.post("/", status_code=201)
def create_list(data: ListCreate):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO lists (user_id, name) VALUES (?, ?)", (1, data.name))
    list_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": list_id, "name": data.name}

@router.get("/")
def get_lists():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM lists WHERE user_id = 1 AND deleted_at IS NULL ORDER BY name")
    lists = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return lists

@router.get("/deleted")
def get_deleted_lists():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, deleted_at 
        FROM lists 
        WHERE user_id = 1 AND deleted_at IS NOT NULL
        ORDER BY deleted_at DESC
    """)
    lists = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return lists

@router.delete("/{list_id}")
def soft_delete_list(list_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1 AND deleted_at IS NULL", (list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Active list not found")
    cursor.execute("UPDATE lists SET deleted_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), list_id))
    conn.commit()
    conn.close()
    return {"message": "List soft-deleted"}

@router.post("/{list_id}/restore")
def restore_list(list_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1 AND deleted_at IS NOT NULL", (list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Deleted list not found")
    cursor.execute("UPDATE lists SET deleted_at = NULL WHERE id = ?", (list_id,))
    conn.commit()
    conn.close()
    return {"message": "List restored"}

@router.post("/deleted/purge")
def purge_old_deleted_lists():
    conn = get_db()
    cursor = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    cursor.execute("SELECT id FROM lists WHERE user_id = 1 AND deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
    ids_to_purge = [row[0] for row in cursor.fetchall()]
    if ids_to_purge:
        placeholders = ','.join('?' * len(ids_to_purge))
        cursor.execute(f"DELETE FROM ratings WHERE list_id IN ({placeholders})", ids_to_purge)
        cursor.execute(f"DELETE FROM list_restaurants WHERE list_id IN ({placeholders})", ids_to_purge)
        cursor.execute(f"DELETE FROM lists WHERE id IN ({placeholders})", ids_to_purge)
    conn.commit()
    conn.close()
    return {"purged_count": len(ids_to_purge)}

@router.post("/{list_id}/add_restaurant")
def add_restaurant_to_list(list_id: int, data: AddRestaurantToList):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM lists WHERE id = ? AND user_id = 1", (list_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="List not found")
    cursor.execute("SELECT id FROM restaurants WHERE id = ?", (data.restaurant_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Restaurant not found")
    cursor.execute("INSERT OR IGNORE INTO list_restaurants (list_id, restaurant_id) VALUES (?, ?)", (list_id, data.restaurant_id))
    conn.commit()
    conn.close()
    return {"message": "Restaurant added to list"}