# API_endpoints/lifespan.py
import subprocess
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .routes.misc_housekeeping import purge_old_discovery_sessions
from datetime import datetime, timedelta, timezone
from .database import get_db

@asynccontextmanager
async def lifespan(app=FastAPI):
    """Handle startup/shutdown events."""
    print("Running startup maintenance...")
    
    # 1. Purge old discovery sessions (6 months)
    discovery_purged = purge_old_discovery_sessions()
    print(f"Purged {discovery_purged} old discovery sessions")

    PROJECT_ROOT = Path(__file__).parent.parent.resolve()
    # 2. Retrain model if new discovery data exists
    try:
        result = subprocess.run(
            [sys.executable, "data/ML_recs/retrain.py"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            print("Model retraining completed")
        else:
            print(f"Retraining failed: {result.stderr}")
    except Exception as e:
        print(f"Retraining error: {e}")
    
    yield 

def purge_old_discovery_sessions():
    """Permanently delete discovery sessions older than 6 months."""
    conn = get_db()
    cursor = conn.cursor()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    
    # Get discovery list IDs
    cursor.execute("""
        SELECT id FROM lists 
        WHERE name LIKE 'Discovery: %' AND created_at < ?
    """, (cutoff,))
    list_ids = [row[0] for row in cursor.fetchall()]
    
    if not list_ids:
        conn.close()
        return 0
    
    placeholders = ','.join('?' * len(list_ids))
    
    # Delete from processed_ratings first (composite key)
    cursor.execute(f"""
        DELETE FROM processed_ratings 
        WHERE list_id IN ({placeholders})
    """, list_ids)
    
    # Delete ratings
    cursor.execute(f"""
        DELETE FROM ratings 
        WHERE list_id IN ({placeholders})
    """, list_ids)
    
    # Delete lists
    cursor.execute(f"""
        DELETE FROM lists 
        WHERE id IN ({placeholders})
    """, list_ids)
    
    count = len(list_ids)
    conn.commit()
    conn.close()
    return count