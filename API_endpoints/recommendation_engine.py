# services/recommendation_engine.py
from typing import List, Dict, Any
from .utils import haversine_distance
from typing import Set
from .database import get_db
import os
import xgboost as xgb

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "rating_model.json")
xgb_model = xgb.XGBRegressor()
xgb_model.load_model(MODEL_PATH)

def load_candidate_restaurants(user_lat: float, user_lng: float, max_meters: float) -> List[Dict]:
    """Load operational restaurants within distance (meters) of user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.id, r.name, r.latitude, r.longitude,
            s.cuisine, s.price_tier, s.has_outdoor_seating,
            s.is_vegan_friendly, s.good_for_dates,
            s.good_for_groups, s.quiet_ambiance, s.has_cocktails
        FROM restaurants r
        JOIN synthetic_attributes s ON r.id = s.place_id
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

# 1/11/26 ML-guided recommendations WIP 

def build_restaurant_features(restaurant: dict, context: str) -> list:
    """
    Build feature vector matching training format.
    Order must match XGBoost's expected features.
    """
    features = []
    
    # Price tier (int)
    features.append(float(restaurant["price_tier"]))
    
    # Cuisine one-hot encoding
    cuisines = [
        "mexican", "italian", "american", "chinese", "japanese",
        "thai", "indian", "french", "mediterranean", "korean",
        "vietnamese", "spanish", "greek", "peruvian", "ethiopian"
    ]
    for c in cuisines:
        features.append(1.0 if restaurant["cuisine"] == c else 0.0)
    
    # Boolean attributes
    bool_attrs = [
        "has_outdoor_seating", "good_for_dates", "is_vegan_friendly",
        "good_for_groups", "quiet_ambiance", "has_cocktails"
    ]
    for attr in bool_attrs:
        features.append(1.0 if restaurant.get(attr, False) else 0.0)
    
    # Context one-hot
    contexts = ["Date Night", "Group Hang", "Quick Lunch", "Weekend Brunch", "Late Night Eats"]
    for ctx in contexts:
        features.append(1.0 if context == ctx else 0.0)
    
    return features

def select_best_question_ml(candidates: List[Dict], session) -> tuple:
    """
    Select question that maximizes expected rating of top recommendation.
    """
    if len(candidates) <= 1:
        return ("complete", "We found your match!", [])
    
    question_order = [
    "price_tier", "cuisine", "has_outdoor_seating", "good_for_dates",
    "is_vegan_friendly", "good_for_groups", "quiet_ambiance", "has_cocktails"
    ]
    asked_attrs = set(session["questions_asked"]) 
    
    best_attr = None
    best_expected_rating = -1
    
    for attr in question_order:
        if attr in asked_attrs:
            continue
            
        # Get values that exist in current candidates
        unique_vals = {c[attr] for c in candidates}
        if len(unique_vals) <= 1:
            continue
        
        total_rating = 0
        valid_answers = 0  # ← track how many answers lead to non-empty sets
        
        for val in unique_vals:
            filtered = [c for c in candidates if c[attr] == val]
            if not filtered:  # skip empty splits
                continue
                
            valid_answers += 1
            top_candidate = filtered[0]
            feat_vec = build_restaurant_features(top_candidate, session["context"])
            pred = xgb_model.predict([feat_vec])[0]
            total_rating += pred
        
        if valid_answers == 0:  # no valid answers
            continue
            
        avg_rating = total_rating / valid_answers
        if avg_rating > best_expected_rating:
            best_expected_rating = avg_rating
            best_attr = attr
    
    if best_attr is None:
        return ("complete", "All options are similar!", [])
    
    # Add to session after selection
    return build_question(best_attr, unique_vals)