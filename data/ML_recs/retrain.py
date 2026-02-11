# retrain.py
import os
import sys
import json
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit

# Add project root to path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from data.data_loader import load_restaurants_from_db
from backend.database import get_db
from train_model import (
    engineer_features,
    evaluate_grouped_ranking_metrics,
    RANK_K_VALUES,
    RELEVANCE_THRESHOLD,
)

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
    
    # 3. Engineer features
    restaurants = load_restaurants_from_db()
    X = engineer_features(full_df, restaurants)
    y = full_df["rating"]
    X = X.fillna(0)
    feature_names = X.columns.tolist()

    # 4. Evaluation on grouped held-out split (same style as train_model).
    groups = pd.util.hash_pandas_object(X, index=False).astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    eval_model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        objective="reg:squarederror",
    )
    eval_model.fit(X_train, y_train)

    y_pred = eval_model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    y_test_bin = (y_test >= RELEVANCE_THRESHOLD).astype(int)
    if y_test_bin.nunique() > 1:
        auc = roc_auc_score(y_test_bin, y_pred)
        auc_msg = f"{auc:.3f}"
    else:
        auc_msg = "N/A (single class in test split)"

    print("\nRetrain eval results:")
    print(f"MAE: {mae:.3f} (lower = better)")
    print(f"AUC (>={RELEVANCE_THRESHOLD}): {auc_msg} (higher = better)")

    eval_df = full_df.iloc[test_idx][["user_id", "context", "rating"]].copy()
    eval_df["pred"] = y_pred
    for k in RANK_K_VALUES:
        rank_metrics = evaluate_grouped_ranking_metrics(
            eval_df,
            k=k,
            relevance_threshold=RELEVANCE_THRESHOLD,
        )
        ndcg_msg = f"{rank_metrics['ndcg']:.3f}" if not np.isnan(rank_metrics["ndcg"]) else "N/A"
        hit_msg = f"{rank_metrics['hit_rate']:.3f}" if not np.isnan(rank_metrics["hit_rate"]) else "N/A"
        print(f"NDCG@{k}: {ndcg_msg} (groups={rank_metrics['ndcg_groups']})")
        print(
            f"Hit-rate@{k} (rating>={RELEVANCE_THRESHOLD}): "
            f"{hit_msg} (eligible_groups={rank_metrics['eligible_hit_groups']})"
        )

    # 5. Train final model on all data and persist artifacts.
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        objective="reg:squarederror",
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
