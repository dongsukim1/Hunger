import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, roc_auc_score
import xgboost as xgb
from data.data_loader import load_restaurants_from_db

# Paths
DATA_PATH = "data/synthetic_ratings1.csv"
DB_PATH = "data/restaurants.db"
MODEL_PATH = "./rating_model.json"

def engineer_features(df, restaurant_list):
    """
    df: synthetic ratings DataFrame [user_id, context, restaurant_id, rating]
    restaurant_list: list of dicts from load_restaurants_from_db()
    """
    # Convert restaurant list to DataFrame
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
    df = df.astype(float)  # bools → 0/1, ints stay ints
    
    return df
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
    feature_names = X.columns.tolist()  # Get feature names from X
    print(f"Engineered {X.shape[1]} features")
    
    # Handle missing values 
    X = X.fillna(0)
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=(y >= 4).astype(int)
    )
    
    print("Training XGBoost model...")
    model = xgb.XGBRegressor(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        random_state=42,
        objective="reg:squarederror"
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    auc = roc_auc_score((y_test >= 4).astype(int), y_pred)
    
    print(f"\n Results:")
    print(f"MAE: {mae:.3f} (lower = better)")
    print(f"AUC (≥4): {auc:.3f} (higher = better)")
    
    # Save model
    model.save_model(MODEL_PATH)
    print(f"\n Model saved to {MODEL_PATH}")
    
    # Feature importance
    importance = pd.DataFrame({
        "feature": feature_names,  
        "importance": model.feature_importances_
    }).sort_values("importance", ascending=False)
    
    print("\nTop 10 important features:")
    print(importance.head(10))
if __name__ == "__main__":
    main()