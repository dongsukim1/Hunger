# evaluate_heuristic.py
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score

df = pd.read_csv("data/synthetic_ratings1.csv")

# Heuristic assumes all recommendations are "good" → predict 4.0
heuristic_predictions = [4.0] * len(df)
true_ratings = df["rating"].tolist()

mae = mean_absolute_error(true_ratings, heuristic_predictions)
auc = roc_auc_score(
    [1 if r >= 4 else 0 for r in true_ratings],
    heuristic_predictions
)

print(f"Heuristic MAE: {mae:.3f}")
print(f"Heuristic AUC: {auc:.3f}")
print(f"% ≥4★: {sum(r>=4 for r in true_ratings)/len(true_ratings)*100:.1f}%")