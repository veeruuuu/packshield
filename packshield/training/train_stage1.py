"""
Stage-1 fusion model training: HistGradientBoostingClassifier over S1
(name similarity) + S4 (publisher/registry features) + s4_registry_status.

Per PROJECT.md Sec 9: primary metric is recall @ fixed low FPR (not raw
accuracy, which is misleading given the ~5.5:1 malicious:benign ratio in
this data -- real-world base rate is the opposite direction, ~1:10,000).
Per-attack-type breakdown (T1/T2/T3/UNKNOWN) is reported separately, since
an easy-T1-win can otherwise mask other categories underperforming.

KNOWN LIMITATION, carried over from prepare_features.py: this uses a
stratified RANDOM split, not the temporal split Sec 9 asks for -- absolute
fetch timestamps were never captured, only relative day-counts, so a real
temporal split isn't reconstructable from what's stored. Flagged, not
silently substituted.

Usage:
    python -m packshield.training.train_stage1 data\stage1_full_features.csv
"""

import argparse
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_curve, confusion_matrix


NUMERIC_FEATURES = [
    "s1_score",
    "package_age_days",
    "days_since_last_publish",
    "total_versions",
    "versions_last_90_days",
    "maintainer_count",
    "weekly_downloads",
]
CATEGORICAL_FEATURES = []  # s4_registry_status removed: leaks takedown status,
                            # which cannot occur at real inference time (a
                            # package being installed right now necessarily
                            # exists on the registry). See PROJECT.md log.


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df["s4_registry_status"] == "resolved"].copy()
    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["label_bin"] = (df["label"] == "malicious").astype(int)
    return df


def recall_at_fpr(y_true, y_scores, target_fpr: float) -> tuple[float, float]:
    """Returns (recall, actual_fpr_used) at the threshold achieving the
    highest FPR <= target_fpr."""
    fpr, tpr, thresholds = roc_curve(y_true, y_scores)
    valid = fpr <= target_fpr
    if not valid.any():
        return 0.0, 0.0
    idx = np.where(valid)[0][-1]  # highest FPR still under the target
    return tpr[idx], fpr[idx]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path")
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = load_data(args.data_path)

    X = df[NUMERIC_FEATURES].copy()
    y = df["label_bin"].values

    X_train, X_test, y_train, y_test, df_train, df_test = train_test_split(
        X, y, df, test_size=args.test_size, random_state=args.seed, stratify=y
    )

    print(f"Train: {len(X_train)} rows ({y_train.sum()} malicious, {len(y_train) - y_train.sum()} benign)")
    print(f"Test:  {len(X_test)} rows ({y_test.sum()} malicious, {len(y_test) - y_test.sum()} benign)")
    print("NOTE: stratified RANDOM split, not temporal -- see module docstring / PROJECT.md log.")
    print()

    model = HistGradientBoostingClassifier(
        class_weight="balanced",
        random_state=args.seed,
    )
    model.fit(X_train, y_train)

    y_scores = model.predict_proba(X_test)[:, 1]
    y_pred = model.predict(X_test)

    print("=== Overall (test set) ===")
    tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}")

    for target_fpr in (0.01, 0.05, 0.10):
        recall, actual_fpr = recall_at_fpr(y_test, y_scores, target_fpr)
        print(f"Recall @ FPR<={target_fpr:.0%}: {recall:.1%} (actual FPR used: {actual_fpr:.2%})")

    print()
    print("=== Per-attack-type recall (malicious rows only, target FPR<=5% threshold) ===")
    _, threshold_fpr = recall_at_fpr(y_test, y_scores, 0.05)
    fpr, tpr, thresholds = roc_curve(y_test, y_scores)
    idx = np.where(fpr <= 0.05)[0][-1]
    chosen_threshold = thresholds[idx]

    mal_test = df_test[df_test["label_bin"] == 1].copy()
    mal_scores = y_scores[df_test["label_bin"].values == 1]
    mal_test["predicted_malicious"] = (mal_scores >= chosen_threshold)

    for attack_type in ["T1", "T2", "T3", "UNKNOWN"]:
        subset = mal_test[mal_test["attack_type"] == attack_type]
        if len(subset) == 0:
            print(f"  {attack_type}: no test examples")
            continue
        recall = subset["predicted_malicious"].mean()
        print(f"  {attack_type}: recall={recall:.1%} (n={len(subset)})")


    print()
    print("=== Recall by s4_registry_status (malicious rows only, same threshold) ===")
    for status in ["resolved", "not_found", "error"]:
        subset = mal_test[mal_test["s4_registry_status"] == status]
        if len(subset) == 0:
            print(f"  {status}: no test examples")
            continue
        recall = subset["predicted_malicious"].mean()
        print(f"  {status}: recall={recall:.1%} (n={len(subset)})")

    import joblib
    joblib.dump(model, "data/stage1_model.joblib")
    print()
    print("Model saved to data/stage1_model.joblib")


if __name__ == "__main__":
    main()
