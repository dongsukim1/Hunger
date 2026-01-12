import random
import math
from .personas import apply_context_modifiers, get_context_modifier

BOOLEAN_ATTRS = [
    "has_outdoor_seating",
    "good_for_dates",
    "is_vegan_friendly",
    "good_for_groups",
    "quiet_ambiance",
    "has_cocktails"
]

QUESTION_ORDER = ["price_tier", "cuisine"] + BOOLEAN_ATTRS

def sigmoid(x):
    return 1 / (1 + math.exp(-max(-100, min(100, x))))

def sample_answer(attr, user_prefs, context_modifier, noise=0.2):
    adjusted_prefs = apply_context_modifiers(user_prefs, "")  
    
    if attr == "price_tier":
        base = adjusted_prefs["price_bias"]
        if "price_bias" in context_modifier:
            base += context_modifier["price_bias"]
        val = max(1, min(3, round(base + random.uniform(-noise, noise))))
        return int(val)
    
    elif attr == "cuisine":
        # Return most preferred cuisine
        affinities = adjusted_prefs["cuisine_affinities"]
        return max(affinities, key=affinities.get)
    
    elif attr in BOOLEAN_ATTRS:
        pref_score = adjusted_prefs["ambiance_prefs"].get(attr, 0.5)
        if attr in context_modifier:
            pref_score += context_modifier[attr]
        pref_score = max(0.0, min(1.0, pref_score))
        return random.random() < (pref_score + random.uniform(-noise/2, noise/2))
    
    return None

def simulate_session(user_prefs, context_name, restaurants):
    adjusted_prefs = apply_context_modifiers(user_prefs, context_name)
    candidates = [r for r in restaurants if r["cuisine"] in adjusted_prefs["cuisine_affinities"]]
    
    questions_asked = 0
    max_questions = 5
    
    while questions_asked < max_questions and len(candidates) > 3:
        attr = QUESTION_ORDER[questions_asked]
        unique_vals = set(c[attr] for c in candidates if attr in c)
        
        if len(unique_vals) <= 1:
            questions_asked += 1
            continue
        
        context_mod = user_prefs["context_modifiers"].get(context_name, {})
        answer = sample_answer(attr, user_prefs, context_mod)
        
        # Filter candidates
        if attr == "cuisine":
            candidates = [c for c in candidates if c[attr] == answer]
        elif attr in BOOLEAN_ATTRS:
            candidates = [c for c in candidates if c[attr] == answer]
        else:  # price_tier
            candidates = [c for c in candidates if c[attr] == answer]
        
        questions_asked += 1
    
    # Generate ratings
    recommendations = []
    for restaurant in candidates[:3]:
        rating = generate_rating(restaurant, adjusted_prefs)
        recommendations.append((restaurant["id"], rating))
    
    return recommendations

def generate_rating(restaurant, adjusted_prefs):
    score = 0.0
    
    # Price match
    price_diff = abs(restaurant["price_tier"] - adjusted_prefs["price_bias"])
    score += max(0, 1 - price_diff * 0.5)
    
    # Cuisine affinity
    cuisine_aff = adjusted_prefs["cuisine_affinities"].get(restaurant["cuisine"], 0.3)
    score += cuisine_aff
    
    # Boolean attributes
    for attr in BOOLEAN_ATTRS:
        if restaurant.get(attr, False):
            score += adjusted_prefs["ambiance_prefs"].get(attr, 0.5)
    
    # Add noise
    final_score = score + random.gauss(0, 0.8)
    rating = 1 + 4 * sigmoid(final_score - 1.5)
    return min(5, max(1, round(rating)))