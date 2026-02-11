import random
import math
import hashlib
from .personas import apply_context_modifiers

BOOLEAN_ATTRS = [
    "has_outdoor_seating",
    "good_for_dates",
    "is_vegan_friendly",
    "good_for_groups",
    "quiet_ambiance",
    "has_cocktails"
]

QUESTION_ORDER = ["price_tier", "cuisine"] + BOOLEAN_ATTRS

CONTEXT_WEIGHTS = {
    "Date Night": {"price": 0.20, "cuisine": 0.30, "ambiance": 0.50, "popularity": 0.10},
    "Group Hang": {"price": 0.35, "cuisine": 0.30, "ambiance": 0.35, "popularity": 0.10},
    "Quick Lunch": {"price": 0.45, "cuisine": 0.35, "ambiance": 0.20, "popularity": 0.10},
    "Weekend Brunch": {"price": 0.25, "cuisine": 0.30, "ambiance": 0.45, "popularity": 0.10},
    "Late Night Eats": {"price": 0.20, "cuisine": 0.35, "ambiance": 0.45, "popularity": 0.15},
}

def sigmoid(x):
    return 1 / (1 + math.exp(-max(-80, min(80, x))))

def _stable_unit_random(key: str) -> float:
    digest = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF

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

def _restaurant_popularity(restaurant):
    return _stable_unit_random(f"pop:{restaurant.get('id', 0)}")

def _restaurant_quality(restaurant):
    return _stable_unit_random(f"qual:{restaurant.get('id', 0)}")

def _context_weights(context_name):
    return CONTEXT_WEIGHTS.get(context_name, CONTEXT_WEIGHTS["Quick Lunch"])

def compute_match_score(restaurant, adjusted_prefs, context_name):
    weights = _context_weights(context_name)

    price_tier = restaurant.get("price_tier", 2)
    price_match = max(0.0, 1.0 - abs(price_tier - adjusted_prefs["price_bias"]) / 2.0)
    cuisine_match = adjusted_prefs["cuisine_affinities"].get(restaurant.get("cuisine"), 0.25)

    ambiance_match = 0.0
    for attr in BOOLEAN_ATTRS:
        pref = adjusted_prefs["ambiance_prefs"].get(attr, 0.5)
        has_attr = bool(restaurant.get(attr, False))
        ambiance_match += pref if has_attr else (1.0 - pref) * 0.3
    ambiance_match /= len(BOOLEAN_ATTRS)

    score = (
        weights["price"] * price_match
        + weights["cuisine"] * cuisine_match
        + weights["ambiance"] * ambiance_match
    )
    denom = max(0.0001, weights["price"] + weights["cuisine"] + weights["ambiance"])
    return max(0.0, min(1.0, score / denom))

def _answer_compatibility(attr, restaurant, answer):
    if attr == "price_tier":
        return max(0.0, 1.0 - abs(restaurant.get("price_tier", 2) - int(answer)) / 2.0)
    if attr == "cuisine":
        return 1.0 if restaurant.get("cuisine") == answer else 0.25
    if attr in BOOLEAN_ATTRS:
        return 1.0 if bool(restaurant.get(attr, False)) == bool(answer) else 0.2
    return 0.5

def _soft_filter_candidates(candidates, attr, answer, strictness):
    retained = []
    for candidate in candidates:
        compat = _answer_compatibility(attr, candidate, answer)
        keep_prob = max(0.05, min(0.98, (1.0 - strictness) * 0.75 + strictness * compat))
        if random.random() < keep_prob:
            retained.append(candidate)
    return retained

def _weighted_sample_without_replacement(items, k):
    if k <= 0 or not items:
        return []
    pool = items[:]
    chosen = []
    for _ in range(min(k, len(pool))):
        total = sum(max(0.001, weight) for _, weight in pool)
        cutoff = random.random() * total
        running = 0.0
        selected_idx = 0
        for idx, (_, weight) in enumerate(pool):
            running += max(0.001, weight)
            if running >= cutoff:
                selected_idx = idx
                break
        chosen_item, _ = pool.pop(selected_idx)
        chosen.append(chosen_item)
    return chosen

def _expose_candidates(candidates, adjusted_prefs, context_name, top_k):
    scored = []
    for candidate in candidates:
        match = compute_match_score(candidate, adjusted_prefs, context_name)
        popularity = _restaurant_popularity(candidate)
        quality = _restaurant_quality(candidate)
        score = 0.58 * match + 0.20 * popularity + 0.14 * quality + random.gauss(0.0, 0.05)
        scored.append((candidate, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    shortlist = scored[: min(18, len(scored))]
    return _weighted_sample_without_replacement(shortlist, top_k)

def _utility_to_rating(utility):
    # Ordinal cut points keep rating distribution controllable and non-linear.
    if utility < -0.45:
        return 1
    if utility < 0.05:
        return 2
    if utility < 0.65:
        return 3
    if utility < 1.25:
        return 4
    return 5

def generate_rating(restaurant, adjusted_prefs, context_name, generosity_bias=0.0, surprise_rate=0.08, mood=0.0):
    match_score = compute_match_score(restaurant, adjusted_prefs, context_name)
    quality = _restaurant_quality(restaurant)
    popularity = _restaurant_popularity(restaurant)

    utility = (
        -0.25
        + 1.55 * match_score
        + 0.55 * quality
        + 0.20 * popularity
        + generosity_bias
        + mood
        + random.gauss(0.0, 0.35)
    )
    rating = _utility_to_rating(utility)

    # Occasional contradictory behavior for robustness.
    if random.random() < surprise_rate:
        rating = random.choices([1, 2, 3, 4, 5], weights=[0.22, 0.20, 0.16, 0.20, 0.22])[0]
    return rating

def simulate_session(
    user_prefs,
    context_name,
    restaurants,
    max_questions=5,
    top_k=3,
    rating_probability=0.55,
    surprise_rate=0.08,
):
    adjusted_prefs = apply_context_modifiers(user_prefs, context_name)
    candidates = [r for r in restaurants if r.get("cuisine") in adjusted_prefs["cuisine_affinities"]]

    strictness = float(user_prefs.get("strictness", 0.6))
    generosity_bias = float(user_prefs.get("generosity_bias", 0.0))
    mood = random.gauss(0.0, 0.20)

    for question_idx in range(max_questions):
        if len(candidates) <= max(top_k * 2, 6):
            continue

        attr = QUESTION_ORDER[question_idx % len(QUESTION_ORDER)]
        unique_vals = {c.get(attr) for c in candidates if attr in c}
        if len(unique_vals) <= 1:
            continue

        context_mod = user_prefs["context_modifiers"].get(context_name, {})
        answer = sample_answer(attr, user_prefs, context_mod)

        filtered = _soft_filter_candidates(candidates, attr, answer, strictness)
        if filtered:
            candidates = filtered

    exposed = _expose_candidates(candidates, adjusted_prefs, context_name, top_k)

    recommendations = []
    for restaurant in exposed:
        match_score = compute_match_score(restaurant, adjusted_prefs, context_name)
        p_rate = max(0.05, min(0.95, rating_probability + 0.25 * (match_score - 0.5)))
        if random.random() > p_rate:
            continue
        rating = generate_rating(
            restaurant,
            adjusted_prefs,
            context_name,
            generosity_bias=generosity_bias,
            surprise_rate=surprise_rate,
            mood=mood,
        )
        recommendations.append((restaurant["id"], rating))

    return recommendations
