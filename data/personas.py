import random

# Real cuisines from your tag generator (excluding "others")
REAL_CUISINES = [
    "mexican", "italian", "american", "chinese", "japanese",
    "thai", "indian", "french", "mediterranean", "korean",
    "vietnamese", "spanish", "greek", "peruvian", "ethiopian"
]

# Boolean attributes in your restaurant schema
BOOLEAN_ATTRS = [
    "has_outdoor_seating",
    "good_for_dates",
    "is_vegan_friendly",
    "good_for_groups",
    "quiet_ambiance",
    "has_cocktails"
]

CONTEXTS = ["Weekend Brunch", "Date Night", "Quick Lunch", "Group Hang", "Late Night Eats"]

def _sample_context_preferences():
    """
    Sample a per-user context distribution via gamma draws.
    Returns {context: probability}.
    """
    raw = [random.gammavariate(2.0, 1.0) for _ in CONTEXTS]
    total = sum(raw) or 1.0
    return {ctx: weight / total for ctx, weight in zip(CONTEXTS, raw)}

def create_persona(user_id: int):
    """
    Generate a synthetic user persona with base preferences and context modifiers.
    """
    # Base price bias (most users prefer $$)
    price_bias = random.choices(
        population=[1.0, 1.5, 2.0, 2.5, 3.0],
        weights=[0.1, 0.2, 0.4, 0.2, 0.1]
    )[0]
    
    # Cuisine affinities
    cuisine_affinities = {}
    for cuisine in REAL_CUISINES:
        if random.random() < 0.3:  # Strong preference
            affinity = random.uniform(0.7, 1.0)
        elif random.random() < 0.5:  # Mild preference
            affinity = random.uniform(0.4, 0.7)
        else:  # Neutral/dislike
            affinity = random.uniform(0.1, 0.4)
        cuisine_affinities[cuisine] = round(affinity, 2)
    
    # Ambiance preferences
    ambiance_prefs = {}
    for attr in BOOLEAN_ATTRS:
        ambiance_prefs[attr] = round(random.uniform(0.2, 0.8), 2)
    
    base_prefs = {
        "price_bias": price_bias,
        "cuisine_affinities": cuisine_affinities,
        "ambiance_prefs": ambiance_prefs
    }
    
    # Context modifiers
    context_modifiers = {
        "Date Night": {
            "quiet_ambiance": random.uniform(0.3, 0.6),
            "has_cocktails": random.uniform(0.2, 0.5),
            "good_for_dates": random.uniform(0.4, 0.7),
            "price_bias": random.uniform(0.2, 0.5)
        },
        "Group Hang": {
            "good_for_groups": random.uniform(0.4, 0.7),
            "has_outdoor_seating": random.uniform(0.2, 0.5),
            "price_bias": random.uniform(-0.5, -0.2)
        },
        "Quick Lunch": {
            "price_bias": random.uniform(-0.7, -0.3),
            "has_outdoor_seating": random.uniform(-0.4, -0.1)
        },
        "Weekend Brunch": {
            "price_bias": random.uniform(0.3, 0.6),
            "has_outdoor_seating": random.uniform(0.3, 0.6),
            "has_cocktails": random.uniform(0.2, 0.5)
        },
        "Late Night Eats": {
            "price_bias": random.uniform(-0.2, 0.3),
            "quiet_ambiance": random.uniform(-0.5, -0.2)
        }
    }
    
    return {
        "user_id": f"user_{user_id:03d}",
        "base_prefs": base_prefs,
        "context_modifiers": context_modifiers,
        "strictness": round(random.uniform(0.35, 0.9), 3),
        "generosity_bias": round(random.gauss(0.0, 0.22), 3),
        "context_preferences": _sample_context_preferences(),
    }

def apply_context_modifiers(user_prefs, context_name):
    """
    Apply context-specific modifiers to base preferences.
    Returns a new adjusted preferences dict.
    """
    base = user_prefs["base_prefs"]
    modifiers = user_prefs["context_modifiers"].get(context_name, {})
    
    # Copy base prefs to avoid mutation
    adjusted = {
        "price_bias": base["price_bias"],
        "cuisine_affinities": base["cuisine_affinities"].copy(),
        "ambiance_prefs": base["ambiance_prefs"].copy()
    }
    
    # Adjust price bias
    if "price_bias" in modifiers:
        adjusted["price_bias"] = max(1.0, min(3.0, adjusted["price_bias"] + modifiers["price_bias"]))
    
    # Adjust ambiance preferences
    for attr, delta in modifiers.items():
        if attr != "price_bias" and attr in adjusted["ambiance_prefs"]:
            new_val = adjusted["ambiance_prefs"][attr] + delta
            adjusted["ambiance_prefs"][attr] = max(0.0, min(1.0, new_val))
    
    return adjusted

def get_context_modifier(context_name, user_prefs):
    """
    Helper: Get context modifier dict for a given context.
    """
    return user_prefs["context_modifiers"].get(context_name, {})

def sample_user_context(user_prefs):
    """
    Sample one context using user-specific context preferences.
    Falls back to uniform if unavailable.
    """
    context_preferences = user_prefs.get("context_preferences", {})
    if not context_preferences:
        return random.choice(CONTEXTS)

    contexts = list(context_preferences.keys())
    probs = list(context_preferences.values())
    return random.choices(contexts, weights=probs, k=1)[0]
