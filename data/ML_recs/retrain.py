# retrain.py
import os
import sys
import pandas as pd
import xgboost as xgb

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from data.data_loader import load_restaurants_from_db
from API.database import get_db
from train_model import engineer_features

MODEL_PATH = os.path.join(PROJECT_ROOT, "rating_model.json")
MIN_NEW_SESSIONS = 1

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
    full_df = pd.concat([synthetic_df, new_df[["user_id", "restaurant_id", "rating", "context"]]], ignore_index=True)
    
    # 3. Train model
    restaurants = load_restaurants_from_db()
    X = engineer_features(full_df, restaurants)
    y = full_df["rating"]
    
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42
    )
    model.fit(X, y)
    model.save_model(MODEL_PATH)
    
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