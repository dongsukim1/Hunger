# synthetic/generate.py
import random
import argparse
from .personas import create_persona
from .session_simulator import simulate_session
from .data_loader import load_restaurants_from_db
import pandas as pd

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-users", type=int, default=20)
    parser.add_argument("--sessions-per-user", type=int, default=25)
    parser.add_argument("--output", type=str, default="synthetic_ratings.csv")
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
    contexts = ["Weekend Brunch", "Date Night", "Quick Lunch", "Group Hang", "Late Night Eats"]

    for user in users:
        for _ in range(args.sessions_per_user):
            context = random.choice(contexts)
            try:
                recommendations = simulate_session(user, context, restaurants)
                if not recommendations:
                    continue
                for restaurant_id, rating in recommendations:
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

if __name__ == "__main__":
    main()