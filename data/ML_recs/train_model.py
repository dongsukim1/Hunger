import json
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score
from sklearn.model_selection import GroupShuffleSplit
import xgboost as xgb

from data.data_loader import load_restaurants_from_db

# Paths
DATA_PATH = "data/synthetic_ratings1.csv"
MODEL_PATH = "./rating_model.json"
FEATURE_SCHEMA_PATH = "./rating_model_features.json"
RANK_K_VALUES = (3, 5)
RELEVANCE_THRESHOLD = 4


def engineer_features(df, restaurant_list):
    """
    df: synthetic ratings DataFrame [user_id, context, restaurant_id, rating]
    restaurant_list: list of dicts from load_restaurants_from_db()
    """
    restaurants_df = pd.DataFrame(restaurant_list)

    # Merge restaurant attributes
    df = df.merge(restaurants_df, left_on="restaurant_id", right_on="id", how="left")

    # One-hot encode CUISINE and CONTEXT
    df = pd.get_dummies(df, columns=["cuisine", "context"], prefix=["cuisine", "context"])

    # Drop all non-feature columns (including 'name', 'id')
    cols_to_drop = ["user_id", "restaurant_id", "id", "name", "rating"]
    for col in cols_to_drop:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Ensure all remaining columns are numeric
    df = df.astype(float)
    return df


def _dcg(relevances):
    vals = np.asarray(relevances, dtype=float)
    if vals.size == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, vals.size + 2))
    gains = (2.0 ** vals - 1.0) * discounts
    return float(np.sum(gains))


def _ndcg_at_k(y_true, y_pred, k):
    if len(y_true) == 0:
        return np.nan
    k_eff = min(int(k), len(y_true))
    order_pred = np.argsort(np.asarray(y_pred))[::-1][:k_eff]
    order_ideal = np.argsort(np.asarray(y_true))[::-1][:k_eff]
    dcg = _dcg(np.asarray(y_true)[order_pred])
    idcg = _dcg(np.asarray(y_true)[order_ideal])
    if idcg <= 0:
        return np.nan
    return dcg / idcg


def evaluate_grouped_ranking_metrics(eval_df, k, relevance_threshold=4):
    ndcg_vals = []
    hit_vals = []
    eligible_hit_groups = 0

    for _, group in eval_df.groupby(["user_id", "context"]):
        y_true = group["rating"].to_numpy(dtype=float)
        y_pred = group["pred"].to_numpy(dtype=float)
        if len(y_true) < 2:
            continue

        ndcg = _ndcg_at_k(y_true, y_pred, k)
        if not np.isnan(ndcg):
            ndcg_vals.append(ndcg)

        relevant_mask = y_true >= float(relevance_threshold)
        if np.any(relevant_mask):
            eligible_hit_groups += 1
            top_k_idx = np.argsort(y_pred)[::-1][: min(int(k), len(y_pred))]
            hit_vals.append(float(np.any(y_true[top_k_idx] >= float(relevance_threshold))))

    ndcg_mean = float(np.mean(ndcg_vals)) if ndcg_vals else float("nan")
    hit_rate = float(np.mean(hit_vals)) if hit_vals else float("nan")
    return {
        "ndcg": ndcg_mean,
        "ndcg_groups": len(ndcg_vals),
        "hit_rate": hit_rate,
        "hit_groups": len(hit_vals),
        "eligible_hit_groups": eligible_hit_groups,
    }


def main():
    # Load data
    print("Loading synthetic ratings...")
    ratings_df = pd.read_csv(DATA_PATH)
    print(f"Loaded {len(ratings_df)} ratings")

    # Load restaurant data
    print("Loading restaurant data...")
    restaurants = load_restaurants_from_db()
    print(f"Loaded data for {len(restaurants)} restaurants")

    # Engineer features
    print("Engineering features...")
    X = engineer_features(ratings_df, restaurants)
    y = ratings_df["rating"]
    feature_names = X.columns.tolist()
    print(f"Engineered {X.shape[1]} features")

    # Handle missing values
    X = X.fillna(0)

    # Group-wise split by feature signature to reduce leakage from duplicate rows.
    # This ensures identical feature vectors do not appear in both train and test.
    groups = pd.util.hash_pandas_object(X, index=False).astype(str)
    splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(splitter.split(X, y, groups=groups))
    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]

    print("Training XGBoost model...")
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        objective="reg:squarederror",
    )
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    y_test_bin = (y_test >= RELEVANCE_THRESHOLD).astype(int)
    if y_test_bin.nunique() > 1:
        auc = roc_auc_score(y_test_bin, y_pred)
        auc_msg = f"{auc:.3f}"
    else:
        auc = float("nan")
        auc_msg = "N/A (single class in test split)"

    print("\n Results:")
    print(f"MAE: {mae:.3f} (lower = better)")
    print(f"AUC (>={RELEVANCE_THRESHOLD}): {auc_msg} (higher = better)")

    eval_df = ratings_df.iloc[test_idx][["user_id", "context", "rating"]].copy()
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

    # Save model
    model.save_model(MODEL_PATH)
    print(f"\n Model saved to {MODEL_PATH}")

    # Save feature schema so inference uses the exact same column order.
    with open(FEATURE_SCHEMA_PATH, "w", encoding="utf-8") as f:
        json.dump(feature_names, f)
    print(f"Feature schema saved to {FEATURE_SCHEMA_PATH}")

    # Feature importance
    importance = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)

    print("\nTop 10 important features:")
    print(importance.head(10))


if __name__ == "__main__":
    main()
