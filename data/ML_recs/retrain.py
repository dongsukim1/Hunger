# retrain.py
import os
import sys
import json
import pandas as pd
import xgboost as xgb

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from data.data_loader import load_restaurants_from_db
from backend.database import get_db
from train_model import engineer_features

MODEL_PATH = os.path.join(PROJECT_ROOT, "rating_model.json")
FEATURE_SCHEMA_PATH = os.path.join(PROJECT_ROOT, "rating_model_features.json")
MIN_NEW_SESSIONS = 1
MODEL_CONTEXTS = [
    "Date Night",
    "Group Hang",
    "Quick Lunch",
    "Weekend Brunch",
    "Late Night Eats",
]

def normalize_context_for_model(raw_context: str) -> str:
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
    return "Quick Lunch"

def retrain_model():
    conn = get_db()
    cursor = conn.cursor()
    
    # Find NEW ratings (not in processed_ratings)
    cursor.execute("""
        SELECT r.user_id, r.restaurant_id, r.list_id, r.rating, l.name as context
        FROM ratings r
        JOIN lists l ON r.list_id = l.id
        WHERE (r.user_id, r.restaurant_id, r.list_id) NOT IN (
            SELECT user_id, restaurant_id, list_id FROM processed_ratings
        )
    """)
    new_ratings = cursor.fetchall()
    
    if len(new_ratings) < MIN_NEW_SESSIONS:
        print("No new ratings. Skipping retrain.")
        conn.close()
        return False
    
    # Create DataFrame
    new_df = pd.DataFrame(
        new_ratings,
        columns=["user_id", "restaurant_id", "list_id", "rating", "context"]
    )
    
    # Combine with synthetic data
    synthetic_df = pd.read_csv("data/synthetic_ratings1.csv")
    new_df["context"] = new_df["context"].map(normalize_context_for_model)
    full_df = pd.concat([synthetic_df, new_df[["user_id", "restaurant_id", "rating", "context"]]], ignore_index=True)
    
    # 3. Train model
    restaurants = load_restaurants_from_db()
    X = engineer_features(full_df, restaurants)
    y = full_df["rating"]
    feature_names = X.columns.tolist()
    
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42
    )
    model.fit(X, y)
    model.save_model(MODEL_PATH)
    with open(FEATURE_SCHEMA_PATH, "w", encoding="utf-8") as f:
        json.dump(feature_names, f)
    
    # Mark new ratings as processed
    for row in new_ratings:
        user_id, restaurant_id, list_id = row[0], row[1], row[2]
        cursor.execute("""
            INSERT INTO processed_ratings (user_id, restaurant_id, list_id)
            VALUES (?, ?, ?)
        """, (user_id, restaurant_id, list_id))
    
    conn.commit()
    conn.close()

    print(f"Model retrained using {len(new_df)} new ratings.")
    return True

if __name__ == "__main__":
    retrain_model()
