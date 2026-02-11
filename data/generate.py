# synthetic/generate.py
import random
import argparse
from .personas import create_persona, sample_user_context
from .session_simulator import simulate_session
from .data_loader import load_restaurants_from_db
import pandas as pd
from data.ML_recs.train_model import engineer_features

def _keep_recommendation(pattern_counts, context, restaurant_id, duplicate_penalty):
    """
    Softly downweight repeated (context, restaurant) pairs to improve feature diversity.
    """
    key = (context, restaurant_id)
    seen = pattern_counts.get(key, 0)
    keep_prob = 1.0 / (1.0 + max(0.0, duplicate_penalty) * seen)
    keep = random.random() < keep_prob
    if keep:
        pattern_counts[key] = seen + 1
    return keep

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-users", type=int, default=20)
    parser.add_argument("--sessions-per-user", type=int, default=25)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-questions", type=int, default=5)
    parser.add_argument("--rating-probability", type=float, default=0.55)
    parser.add_argument("--surprise-rate", type=float, default=0.08)
    parser.add_argument("--preference-drift", type=float, default=0.20)
    parser.add_argument("--exploration-rate", type=float, default=0.22)
    parser.add_argument("--strictness-jitter", type=float, default=0.10)
    parser.add_argument("--duplicate-penalty", type=float, default=0.70)
    parser.add_argument("--output", type=str, default="synthetic_ratings1.csv")
    args = parser.parse_args()

    # Seed everything
    random.seed(args.seed)

    # Load real restaurant data
    restaurants = load_restaurants_from_db()
    if not restaurants:
        raise ValueError("No restaurants loaded! Check your DB path.")
    print(f"Loaded {len(restaurants)} restaurants")

    # Generate user personas
    users = [create_persona(i) for i in range(args.num_users)]
    print(f"Created {len(users)} user personas")

    # Main simulation loop
    dataset = []
    context_counts = {}
    pattern_counts = {}

    for user in users:
        for _ in range(args.sessions_per_user):
            context = sample_user_context(user)
            context_counts[context] = context_counts.get(context, 0) + 1
            try:
                recommendations = simulate_session(
                    user,
                    context,
                    restaurants,
                    max_questions=args.max_questions,
                    top_k=args.top_k,
                    rating_probability=args.rating_probability,
                    surprise_rate=args.surprise_rate,
                    preference_drift=args.preference_drift,
                    exploration_rate=args.exploration_rate,
                    strictness_jitter=args.strictness_jitter,
                )
                if not recommendations:
                    continue
                for restaurant_id, rating in recommendations:
                    if not _keep_recommendation(
                        pattern_counts,
                        context,
                        restaurant_id,
                        duplicate_penalty=args.duplicate_penalty,
                    ):
                        continue
                    dataset.append({
                        "user_id": user["user_id"],
                        "context": context,
                        "restaurant_id": restaurant_id,
                        "rating": rating
                    })
            except Exception as e:
                continue  # silently skip errors
            
    # Save
    df = pd.DataFrame(dataset)
    df.to_csv(args.output, index=False)
    print(f"Saved {len(df)} ratings to {args.output}")
    print_diagnostics(df, restaurants, context_counts)

def print_diagnostics(df, restaurants, context_counts):
    if df.empty:
        print("No rows generated; diagnostics skipped.")
        return

    print("\nDiagnostics:")
    print(f"Sessions by context: {context_counts}")
    counts = df["rating"].value_counts().sort_index()
    print(f"Rating histogram: {counts.to_dict()}")
    pct_ge4 = (df["rating"] >= 4).mean() * 100
    print(f"% ratings >=4: {pct_ge4:.1f}%")

    context_means = df.groupby("context")["rating"].mean().round(3).to_dict()
    print(f"Mean rating by context: {context_means}")

    per_user_counts = df.groupby("user_id").size()
    quantiles = per_user_counts.quantile([0.25, 0.5, 0.75]).to_dict()
    quantiles = {k: round(v, 1) for k, v in quantiles.items()}
    print(f"Ratings/user quantiles (25/50/75): {quantiles}")

    X = engineer_features(df, restaurants).fillna(0)
    dup_frac = float(X.duplicated().mean())
    pair_dup_frac = float(df.duplicated(subset=["context", "restaurant_id"]).mean())
    print(f"Duplicate (context, restaurant) fraction: {pair_dup_frac:.4f}")
    print(f"Duplicate feature-row fraction: {dup_frac:.4f}")

if __name__ == "__main__":
    main()
