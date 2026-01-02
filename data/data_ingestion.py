import requests
import sqlite3
import math
import time
import logging
from typing import List, Tuple, Dict, Any
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY") # GOOGLE_PLACES_API_KEY=your_key_here data_ingestion.py
DB_PATH = "data/restaurants.db"
REQUEST_COUNTER = 0

# Bounding box: [southwest_lat, southwest_lng, northeast_lat, northeast_lng]
# Rough bounding box for Mission District, San Francisco
BBOX = [37.74802895624222, -122.42248265700066, 37.769249996806195, -122.40801467343661]

# Search parameters
RADIUS_METERS = 100  # Google max is 50,000, but we use small radius for density + overlap.
MAX_PAGES_PER_QUERY = 3  # Google returns up to 20 results per page, even if I set this to 3 it will only return 1 page.
REQUEST_DELAY_SEC = 0.1  # Minimum QPS delay.

def create_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY,
            google_place_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            address TEXT,
            price_level INTEGER,
            business_status TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_place_id ON restaurants(google_place_id);")
    conn.commit()
    conn.close()


def generate_grid_points(sw_lat, sw_lng, ne_lat, ne_lng, step_m):
    points = []
    lat = sw_lat
    while lat <= ne_lat:
        lng = sw_lng
        while lng <= ne_lng:
            points.append((lat, lng))
            lng += step_m / (111320 * math.cos(math.radians(lat)))
        lat += step_m / 111320
    return points


def fetch_places_nearby(lat: float, lng: float, radius: int) -> List[Dict[str, Any]]:
    global REQUEST_COUNTER
    all_results = []
    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": (
            "places.id,"
            "places.displayName,"
            "places.location,"
            "places.priceLevel,"
            "places.businessStatus,"
            "places.formattedAddress"
        )   
    }
    payload = {
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius
            }
        },
        "includedPrimaryTypes": ["restaurant"],
        "maxResultCount": 20
    }

    next_page_token = None
    pages_fetched = 0

    while pages_fetched < MAX_PAGES_PER_QUERY:
        if next_page_token:
            payload["pageToken"] = next_page_token
            time.sleep(2)  # Required by Google before using nextPageToken

        try:
            REQUEST_COUNTER += 1
            logger.info(f"Making API request #{REQUEST_COUNTER}")
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            places = data.get("places", [])
            all_results.extend(places)
            logger.info(f"Fetched {len(places)} places at ({lat:.4f}, {lng:.4f})")

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break
            pages_fetched += 1

        except Exception as e:
            logger.error(f"Request failed at ({lat:.4f}, {lng:.4f}): {e}")
            if 'response' in locals():
                logger.error(f"Response content: {response.text}")
            break

        time.sleep(REQUEST_DELAY_SEC)

    return all_results


def insert_restaurants(places: List[Dict[str, Any]]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    inserted = 0

    for p in places:
        place_id = p["id"]
        name = p.get("displayName", {}).get("text", "Unnamed").strip()
        lat = p["location"]["latitude"]
        lng = p["location"]["longitude"] 
        address = p.get("formattedAddress", "") # Street address, City, State, ZIP Country
        price_level = p.get("priceLevel")  # VERY_EXPENSIVE, EXPENSIVE, MODERATE, INEXPENSIVE, NULL
        business_status = p.get("businessStatus", "OPERATIONAL") # OPERATIONAL, CLOSED_TEMPORARILY, CLOSED_PERMANENTLY

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO restaurants (
                    google_place_id, name, latitude, longitude, address, price_level, business_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (place_id, name, lat, lng, address, price_level, business_status))
            if cursor.rowcount > 0:
                inserted += 1
        except Exception as e:
            logger.error(f"Failed to insert {place_id}: {e}")

    conn.commit()
    conn.close()
    logger.info(f"Inserted {inserted} new restaurants (deduplicated by place_id)")


def main():
    create_db()
    grid_points = generate_grid_points(*BBOX, step_m=RADIUS_METERS)
    logger.info(f"Generated {len(grid_points)} grid points over bounding box")

    all_places = []
    for i, (lat, lng) in enumerate(grid_points):
        logger.info(f"Processing point {i+1}/{len(grid_points)}")
        results = fetch_places_nearby(lat, lng, RADIUS_METERS)
        all_places.extend(results)

    # Deduplicate in memory by place ID
    seen = set()
    unique_places = []
    for p in all_places:
        pid = p["id"]
        if pid not in seen:
            seen.add(pid)
            unique_places.append(p)

    logger.info(f"Total unique places fetched: {len(unique_places)}")
    insert_restaurants(unique_places)
    logger.info(f"Ingestion complete. Total Google Places API requests: {REQUEST_COUNTER}")


if __name__ == "__main__":
    main()