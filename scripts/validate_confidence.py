"""Time-series cross-validation for the confidence scoring model.

Validates whether the in-sample AUC (0.825) is real or overfitted by using
expanding-window CV with monthly fold boundaries.

Usage:
    cd /Users/allenqiang/stockagent && python scripts/validate_confidence.py
"""

import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from sqlalchemy import text

from api.models.base import SessionLocal

FEATURE_NAMES = [
    "alpha_score",
    "gamma_score",
    "has_gamma",
    "trend_strength",
    "volatility",
    "index_return_pct",
]

CALIBRATION_BINS = [0, 0.3, 0.5, 0.6, 0.7, 0.8, 1.01]
MIN_FOLD_SAMPLES = 10
IN_SAMPLE_AUC = 0.825


def load_training_data_with_dates():
    """Load training data with month keys for fold splitting.

    Same SQL join as confidence_scorer._build_training_data but also selects
    first_buy_date to derive the fold period (YYYY-MM).
    """
    db = SessionLocal()
    try:
        sql = text("""
            SELECT p.alpha_score, p.gamma_score,
                   mr.trend_strength, mr.volatility, mr.index_return_pct,
                   r.pnl_pct,
                   r.first_buy_date
            FROM bot_trade_plans p
            JOIN bot_trade_reviews r
                ON r.stock_code = p.stock_code
                AND r.strategy_id = p.strategy_id
                AND r.first_buy_date = p.plan_date
            JOIN market_regimes mr
                ON r.first_buy_date BETWEEN mr.week_start::text AND mr.week_end::text
            WHERE p.status = 'executed'
                AND p.direction = 'buy'
                AND p.alpha_score IS NOT NULL
            ORDER BY r.first_buy_date
        """)
        rows = db.execute(sql).fetchall()
    finally:
        db.close()

    if not rows:
        print("ERROR: No training data found. Check database connection and tables.")
        sys.exit(1)

    X_list = []
    y_list = []
    periods = []

    for row in rows:
        alpha_score = float(row[0]) if row[0] is not None else 0.0
        gamma_score = float(row[1]) if row[1] is not None else 0.0
        has_gamma = 1.0 if row[1] is not None else 0.0
        trend_strength = float(row[2]) if row[2] is not None else 0.0
        volatility = float(row[3]) if row[3] is not None else 0.0
        index_return_pct = float(row[4]) if row[4] is not None else 0.0
        pnl_pct = float(row[5]) if row[5] is not None else 0.0
        first_buy_date = str(row[6])  # may be date or string

        X_list.append([
            alpha_score, gamma_score, has_gamma,
            trend_strength, volatility, index_return_pct,
        ])
        y_list.append(1 if pnl_pct > 0 else 0)
        # Extract YYYY-MM as period key
        periods.append(first_buy_date[:7])

    return np.array(X_list), np.array(y_list), periods


def expanding_window_cv(X, y, periods):
    """Expanding-window time-series cross-validation.

    For each unique month (sorted chronologically), train on all prior months
    and test on the current month. Skip folds with fewer than MIN_FOLD_SAMPLES
    test samples or where training data has no class variance.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.preprocessing import StandardScaler

    unique_periods = sorted(set(periods))
    periods_arr = np.array(periods)

    print(f"Total samples: {len(y)}")
    print(f"Positive rate: {y.mean():.4f}")
    print(f"Unique periods: {len(unique_periods)}")
    print(f"Period range: {unique_periods[0]} to {unique_periods[-1]}")
    print()

    fold_results = []
    skipped = 0

    # Need at least 2 periods: first for training, rest for testing
    for i in range(1, len(unique_periods)):
        train_periods = set(unique_periods[:i])
        test_period = unique_periods[i]

        train_mask = np.array([p in train_periods for p in periods])
        test_mask = periods_arr == test_period

        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]

        # Skip small test folds
        if len(y_test) < MIN_FOLD_SAMPLES:
            skipped += 1
            continue

        # Skip if no class variance in training data
        if y_train.mean() == 0.0 or y_train.mean() == 1.0:
            skipped += 1
            continue

        # Skip if no class variance in test data (AUC undefined)
        if y_test.mean() == 0.0 or y_test.mean() == 1.0:
            skipped += 1
            continue

        # Train
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)

        lr = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
        lr.fit(X_train_scaled, y_train)

        proba_test = lr.predict_proba(X_test_scaled)[:, 1]
        auc = roc_auc_score(y_test, proba_test)
        brier = brier_score_loss(y_test, proba_test)

        fold_results.append({
            "period": test_period,
            "train_size": len(y_train),
            "test_size": len(y_test),
            "auc": auc,
            "brier": brier,
            "test_pos_rate": float(y_test.mean()),
            "proba_test": proba_test,
            "y_test": y_test,
        })

    return fold_results, skipped


def compute_calibration(fold_results):
    """Compute calibration bins across all folds."""
    all_proba = np.concatenate([f["proba_test"] for f in fold_results])
    all_y = np.concatenate([f["y_test"] for f in fold_results])

    print("Calibration (pooled across folds):")
    print(f"  {'Bin':>12s}  {'Count':>6s}  {'Pred':>8s}  {'Actual':>8s}  {'Gap':>8s}")
    print(f"  {'-'*12}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}")

    for j in range(len(CALIBRATION_BINS) - 1):
        lo, hi = CALIBRATION_BINS[j], CALIBRATION_BINS[j + 1]
        mask = (all_proba >= lo) & (all_proba < hi)
        n = mask.sum()
        if n == 0:
            print(f"  [{lo:.1f}, {hi:.2f})  {0:>6d}  {'n/a':>8s}  {'n/a':>8s}  {'n/a':>8s}")
            continue
        pred_mean = all_proba[mask].mean()
        actual_mean = all_y[mask].mean()
        gap = actual_mean - pred_mean
        print(f"  [{lo:.1f}, {hi:.2f})  {n:>6d}  {pred_mean:>8.4f}  {actual_mean:>8.4f}  {gap:>+8.4f}")

    print()


def compute_insample_metrics(X, y):
    """Compute in-sample AUC and Brier for comparison."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    lr = LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs")
    lr.fit(X_scaled, y)
    proba = lr.predict_proba(X_scaled)[:, 1]
    auc = roc_auc_score(y, proba)
    brier = brier_score_loss(y, proba)
    return auc, brier


def main():
    print("=" * 64)
    print("  Confidence Model Time-Series Cross-Validation")
    print("=" * 64)
    print()

    # 1. Load data
    X, y, periods = load_training_data_with_dates()

    # 2. In-sample metrics
    insample_auc, insample_brier = compute_insample_metrics(X, y)
    print(f"In-sample AUC:   {insample_auc:.4f}  (reference: {IN_SAMPLE_AUC})")
    print(f"In-sample Brier: {insample_brier:.4f}")
    print()

    # 3. Expanding-window CV
    print("-" * 64)
    print("  Expanding-Window Time-Series CV (monthly folds)")
    print("-" * 64)
    print()

    fold_results, skipped = expanding_window_cv(X, y, periods)

    if not fold_results:
        print("ERROR: No valid folds. Need more data (>= 2 months, >= 10 test samples each).")
        sys.exit(1)

    # 4. Print per-fold results
    print(f"Valid folds: {len(fold_results)}, skipped: {skipped}")
    print()
    print(f"  {'Period':>8s}  {'Train':>6s}  {'Test':>5s}  {'AUC':>7s}  {'Brier':>7s}  {'TestPR':>7s}")
    print(f"  {'-'*8}  {'-'*6}  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}")

    for f in fold_results:
        print(
            f"  {f['period']:>8s}  {f['train_size']:>6d}  {f['test_size']:>5d}"
            f"  {f['auc']:>7.4f}  {f['brier']:>7.4f}  {f['test_pos_rate']:>7.3f}"
        )

    # 5. Summary statistics
    aucs = np.array([f["auc"] for f in fold_results])
    briers = np.array([f["brier"] for f in fold_results])
    test_sizes = np.array([f["test_size"] for f in fold_results])

    # Weighted average by test size
    cv_auc_weighted = np.average(aucs, weights=test_sizes)
    cv_brier_weighted = np.average(briers, weights=test_sizes)
    cv_auc_mean = aucs.mean()
    cv_auc_std = aucs.std()

    print()
    print("-" * 64)
    print("  Summary")
    print("-" * 64)
    print()
    print(f"  CV AUC (mean +/- std):     {cv_auc_mean:.4f} +/- {cv_auc_std:.4f}")
    print(f"  CV AUC (weighted):         {cv_auc_weighted:.4f}")
    print(f"  CV Brier (weighted):       {cv_brier_weighted:.4f}")
    print(f"  In-sample AUC:             {insample_auc:.4f}")
    print(f"  AUC drop (in-sample - CV): {insample_auc - cv_auc_weighted:.4f}")
    print()

    # 6. Calibration
    print("-" * 64)
    print("  Calibration Analysis")
    print("-" * 64)
    print()
    compute_calibration(fold_results)

    # 7. Verdict
    print("=" * 64)
    if cv_auc_weighted >= 0.80:
        verdict = "GENUINELY STRONG"
        detail = (
            f"CV AUC {cv_auc_weighted:.4f} >= 0.80. "
            f"The model generalizes well out-of-sample. "
            f"AUC drop from in-sample is only {insample_auc - cv_auc_weighted:.4f}."
        )
    elif cv_auc_weighted >= 0.70:
        verdict = "DECENT"
        detail = (
            f"CV AUC {cv_auc_weighted:.4f} >= 0.70. "
            f"The model has moderate predictive power but shows some overfit "
            f"(drop = {insample_auc - cv_auc_weighted:.4f})."
        )
    else:
        verdict = "OVERFITTED"
        detail = (
            f"CV AUC {cv_auc_weighted:.4f} < 0.70. "
            f"The in-sample AUC ({insample_auc:.4f}) is misleading. "
            f"The model does not generalize well."
        )

    print(f"  VERDICT: {verdict}")
    print(f"  {detail}")
    print("=" * 64)


if __name__ == "__main__":
    main()
