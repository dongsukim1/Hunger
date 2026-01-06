# services/recommendation_engine.py
from typing import List, Dict, Any
from .utils import haversine_distance
from typing import Set
from .database import get_db

def load_candidate_restaurants(user_lat: float, user_lng: float, max_meters: float) -> List[Dict]:
    """Load operational restaurants within distance (meters) of user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.place_id, r.name, r.latitude, r.longitude,
            s.cuisine, s.price_tier, s.has_outdoor_seating,
            s.is_vegan_friendly, s.good_for_dates,
            s.good_for_groups, s.quiet_ambiance, s.has_cocktails
        FROM restaurants r
        JOIN synthetic_attributes s ON r.place_id = s.place_id
        WHERE r.business_status = 'OPERATIONAL'
    """)
    
    candidates = []
    for row in cursor.fetchall():
        dist = haversine_distance(user_lat, user_lng, row["latitude"], row["longitude"])
        if dist <= max_meters:
            candidates.append({**dict(row), "distance_m": dist})
    conn.close()
    return candidates
    
def build_question(attr: str, values: Set[Any]) -> tuple:
    """Return (question_id, question_text, options)"""
    mapping = {
        "price_tier": ("price_tier", "What's your budget?", ["$", "$$", "$$$"]),
        "cuisine": ("cuisine", "What kind of food are you craving?", sorted([str(v) for v in values])),
        "has_outdoor_seating": ("has_outdoor_seating", "Do you want outdoor seating?", ["Yes", "No"]),
        "good_for_dates": ("good_for_dates", "Is this for a date?", ["Yes", "No"]),
        "is_vegan_friendly": ("is_vegan_friendly", "Must it be vegan-friendly?", ["Yes", "No"]),
        "good_for_groups": ("good_for_groups", "Is it for a group (4+ people)?", ["Yes", "No"]),
        "quiet_ambiance": ("quiet_ambiance", "Should it be quiet enough for conversation?", ["Yes", "No"]),
        "has_cocktails": ("has_cocktails", "Do you want a place with cocktails?", ["Yes", "No"]),
    }
    
    if attr in mapping:
        return mapping[attr]
    return ("fallback", "Any other preference?", ["Yes", "No"])

def select_best_question(candidates: List[Dict]) -> tuple:
    if len(candidates) <= 1:
        return ("complete", "We found your match!", [])
    
    # Priority order: most discriminative questions first
    question_order = [
        ("price_tier", lambda c: c["price_tier"]),
        ("cuisine", lambda c: c["cuisine"]),
        ("has_outdoor_seating", lambda c: c["has_outdoor_seating"]),
        ("good_for_dates", lambda c: c["good_for_dates"]),
        ("is_vegan_friendly", lambda c: c["is_vegan_friendly"]),
        ("good_for_groups", lambda c: c["good_for_groups"]),
        ("quiet_ambiance", lambda c: c["quiet_ambiance"]),
        ("has_cocktails", lambda c: c["has_cocktails"]),
    ]
    
    for attr, extractor in question_order:
        unique_vals = {extractor(c) for c in candidates}
        if len(unique_vals) > 1:
            return build_question(attr, unique_vals)
    
    # All attributes identical
    return ("complete", "All remaining options are similar!", [])

def filter_candidates(candidates: List[Dict], question_id: str, answer: str) -> List[Dict]:
    """Filter candidates based on answer to question_id"""
    if question_id == "price_tier":
        tier_map = {"$": 1, "$$": 2, "$$$": 3}
        target_tier = tier_map.get(answer, 2)
        return [c for c in candidates if c["price_tier"] == target_tier]
    
    # Boolean questions
    bool_questions = {
        "has_outdoor_seating",
        "good_for_dates",
        "is_vegan_friendly",
        "good_for_groups",
        "quiet_ambiance",
        "has_cocktails"
    }
    
    if question_id in bool_questions:
        target = (answer.lower() == "yes")
        return [c for c in candidates if c[question_id] == target]
    
    # Cuisine
    if question_id == "cuisine":
        return [c for c in candidates if c["cuisine"] == answer]
    
    return candidates  # fallback