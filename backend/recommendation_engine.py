# recommendation_engine.py
from typing import List, Dict, Any
from .utils import haversine_distance
from typing import Set
import os
import json
import threading
import xgboost as xgb
from data.data_loader import load_restaurants_from_db

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "rating_model.json")
FEATURE_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "rating_model_features.json")
xgb_model = xgb.XGBRegressor()
FEATURE_SCHEMA = []
MODEL_LOCK = threading.Lock()

def reload_model_artifacts():
    """
    Reload model + feature schema from disk so inference can pick up retrains
    without a process restart.
    """
    global FEATURE_SCHEMA
    with MODEL_LOCK:
        xgb_model.load_model(MODEL_PATH)
        with open(FEATURE_SCHEMA_PATH, "r", encoding="utf-8") as f:
            FEATURE_SCHEMA = json.load(f)

reload_model_artifacts()

MODEL_CONTEXTS = [
    "Date Night",
    "Group Hang",
    "Quick Lunch",
    "Weekend Brunch",
    "Late Night Eats",
]

def normalize_context_for_model(raw_context: str) -> str:
    """
    Map free-form session/list contexts to the model's known context labels.
    """
    if raw_context in MODEL_CONTEXTS:
        return raw_context

    value = (raw_context or "").strip().lower()
    if any(token in value for token in ["date", "anniversary", "romantic"]):
        return "Date Night"
    if any(token in value for token in ["group", "friends", "party", "hang"]):
        return "Group Hang"
    if any(token in value for token in ["brunch", "weekend", "breakfast"]):
        return "Weekend Brunch"
    if any(token in value for token in ["late", "night", "bar", "after"]):
        return "Late Night Eats"
    if any(token in value for token in ["lunch", "work", "quick"]):
        return "Quick Lunch"

    # Safe fallback when context is unknown (e.g., "Discovery Session").
    return "Quick Lunch"

def load_candidate_restaurants(user_lat: float, user_lng: float, max_meters: float) -> List[Dict]:
    """Load operational restaurants within distance (meters) of user."""
    rows = load_restaurants_from_db(include_location=True)
    candidates = []
    for row in rows:
        dist = haversine_distance(user_lat, user_lng, row["latitude"], row["longitude"])
        if dist <= max_meters:
            candidates.append({**dict(row), "distance_m": dist})
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
    Build feature vector using the saved training schema.
    This avoids manual column-order drift between training and inference.
    """
    feature_values = {name: 0.0 for name in FEATURE_SCHEMA}
    normalized_context = normalize_context_for_model(context)

    if "price_tier" in feature_values:
        feature_values["price_tier"] = float(restaurant.get("price_tier", 0) or 0)

    for name in FEATURE_SCHEMA:
        if name.startswith("cuisine_"):
            feature_values[name] = 1.0 if restaurant.get("cuisine") == name.replace("cuisine_", "", 1) else 0.0
        elif name.startswith("context_"):
            feature_values[name] = 1.0 if normalized_context == name.replace("context_", "", 1) else 0.0
        elif name in restaurant:
            feature_values[name] = 1.0 if bool(restaurant.get(name)) else 0.0

    return [feature_values[name] for name in FEATURE_SCHEMA]

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
    best_values = set()
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
            with MODEL_LOCK:
                pred = xgb_model.predict([feat_vec])[0]
            total_rating += pred
        
        if valid_answers == 0:  # no valid answers
            continue
            
        avg_rating = total_rating / valid_answers
        if avg_rating > best_expected_rating:
            best_expected_rating = avg_rating
            best_attr = attr
            best_values = unique_vals
    
    if best_attr is None:
        return ("complete", "All options are similar!", [])
    
    # Add to session after selection
    return build_question(best_attr, best_values)
