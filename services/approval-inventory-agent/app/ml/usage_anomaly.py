"""
Runtime usage anomaly scorer for the Approval & Inventory Intelligence Agent.

Loads the trained IsolationForest model (ml/artifacts/model.joblib) lazily on
first call and caches it for the process lifetime.

Public API
──────────
    scorer = UsageAnomalyScorer()
    result = scorer.score(license_id, sso_events, total_seats)
    # result = {
    #     "anomaly_score": 0.72,           # 0 = normal, 1 = maximally anomalous
    #     "model_version": "v20260902...",
    #     "top_factors": [
    #         {"feature": "dod_rate_change",      "contribution": 0.31},
    #         {"feature": "days_since_last_login", "contribution": 0.18},
    #         {"feature": "active_seats_30d",      "contribution": -0.09},
    #     ]
    # }

SHAP explainability
───────────────────
IsolationForest has no built-in feature_importances_, so we use
shap.TreeExplainer (which supports tree-based ensembles natively).

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)   # shape (1, n_features)
    # Positive SHAP → feature pushes the instance toward anomaly
    # Negative SHAP → feature pushes the instance toward normal/inlier

Top factors are sorted by |SHAP| descending; we return the top N_TOP (3).
Contribution is the raw SHAP value (not absolute), so the caller can tell
the direction.  This matches the {feature, contribution} shape already used
by risk.score.updated.

Score normalisation
───────────────────
IsolationForest.score_samples() returns raw scores in (-∞, 0].  We stored
score_min and score_max at training time in the artifact bundle and use the
same linear transform here so scores are comparable across re-trains:

    anomaly_score = (score_max - raw) / (score_max - score_min)   clamped [0, 1]
"""
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Artifact paths ─────────────────────────────────────────────────────────────
# app/ml/usage_anomaly.py → go up to app/ → approval-inventory-agent/ → ml/artifacts/
_HERE         = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.join(_HERE, "..", "..")           # services/approval-inventory-agent/
_ML_ARTIFACTS = os.path.join(_SERVICE_ROOT, "ml", "artifacts")
MODEL_PATH    = os.path.join(_ML_ARTIFACTS, "model.joblib")

# How many top SHAP contributors to surface
N_TOP = 3


class UsageAnomalyScorer:
    """Thread-safe singleton that loads the IsolationForest model once and re-uses it.

    Instantiate once at application startup (e.g., on the FastAPI app state)
    or let UsageService create one per process.  Multiple calls to score()
    are safe from concurrent async contexts because the load is protected by
    a threading.Lock and the model itself is read-only after loading.
    """

    _instance_lock = threading.Lock()
    _bundle = None          # Loaded once; {model, features, score_min, score_max, ...}
    _shap_explainer = None  # shap.TreeExplainer — may be None if shap not installed

    # ── Model loading ──────────────────────────────────────────────────────────

    @classmethod
    def _load(cls) -> bool:
        """Load the model bundle from disk.  No-op if already loaded.

        Returns True if the model is available (loaded now or previously),
        False if the artifact file doesn't exist yet.
        """
        with cls._instance_lock:
            if cls._bundle is not None:
                return True
            if not os.path.exists(MODEL_PATH):
                logger.warning(
                    f"Usage anomaly model not found at {MODEL_PATH}. "
                    "Run: python ml/train_usage_anomaly_model.py"
                )
                return False
            try:
                import joblib
                cls._bundle = joblib.load(MODEL_PATH)
                logger.info(
                    f"Loaded usage anomaly model {cls._bundle.get('version', 'unknown')}"
                    f" from {MODEL_PATH}"
                )
            except Exception as e:
                logger.error(f"Failed to load usage anomaly model: {e}", exc_info=True)
                return False

            # Try to get the SHAP explainer that was stored in the bundle at
            # training time.  If it's missing (e.g., shap wasn't installed when
            # training ran), reconstruct it now.
            cls._shap_explainer = cls._bundle.get("shap_explainer")
            if cls._shap_explainer is None:
                try:
                    import shap
                    cls._shap_explainer = shap.TreeExplainer(cls._bundle["model"])
                    logger.info("Reconstructed shap.TreeExplainer from loaded model")
                except ImportError:
                    logger.warning(
                        "shap not installed — top_factors will be empty. "
                        "Install: pip install shap"
                    )
                except Exception as e:
                    logger.warning(f"Could not build shap.TreeExplainer: {e}")
            return True

    @classmethod
    def reload(cls):
        """Force a model reload on the next score() call (e.g., after re-training)."""
        with cls._instance_lock:
            cls._bundle = None
            cls._shap_explainer = None

    # ── Feature engineering (single-license, runtime) ─────────────────────────

    @staticmethod
    def _engineer(
        sso_events: list[dict],
        total_seats: int,
        now: Optional[datetime] = None,
    ) -> tuple[np.ndarray, list[str]]:
        """Produce the 9-feature vector for one license at runtime.

        This is intentionally kept in sync with ml/generate_usage_dataset.py
        so that the runtime features match exactly what the model was trained on.

        Args:
            sso_events: All SSO events for this license in the last 90 days.
            total_seats: Total licensed seats (denominator for utilisation_ratio).
            now: Reference timestamp; defaults to UTC now.

        Returns:
            (feature_vector, feature_names) — shapes (1, 9) and (9,).
        """
        from datetime import timedelta
        from collections import defaultdict

        if now is None:
            now = datetime.now(timezone.utc)

        cutoff_7d  = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)
        cutoff_90d = now - timedelta(days=90)

        FEATURE_COLUMNS = [
            "active_seats_7d",
            "active_seats_30d",
            "active_seats_90d",
            "utilisation_ratio",
            "dod_rate_change",
            "wow_rate_change",
            "variance_daily_logins",
            "days_since_last_login",
            "weekend_ratio",
        ]

        parsed = []
        for ev in sso_events:
            try:
                ts_raw = ev.get("login_timestamp") or ev.get("ts")
                if not ts_raw:
                    continue
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff_90d:
                    parsed.append((ts, ev.get("user_email", "")))
            except Exception:
                continue

        if not parsed:
            # No events → zero vector (maximally anomalous by construction)
            return np.zeros((1, len(FEATURE_COLUMNS))), FEATURE_COLUMNS

        users_7d  = {u for ts, u in parsed if ts >= cutoff_7d}
        users_30d = {u for ts, u in parsed if ts >= cutoff_30d}
        users_90d = {u for ts, u in parsed}

        active_7d  = len(users_7d)
        active_30d = len(users_30d)
        active_90d = len(users_90d)
        utilisation_ratio = active_30d / max(total_seats, 1)

        # Daily login counts
        daily: defaultdict[datetime, int] = defaultdict(int)
        for ts, _ in parsed:
            day_key = ts.replace(hour=0, minute=0, second=0, microsecond=0)
            daily[day_key] += 1

        all_days = sorted(
            {cutoff_90d + timedelta(days=i) for i in range(91)} | set(daily.keys())
        )
        counts_series = np.array([daily.get(d, 0) for d in all_days])
        variance_daily = float(np.var(counts_series)) if len(counts_series) > 1 else 0.0

        # Day-over-day (30d window)
        recent_days = sorted({cutoff_30d + timedelta(days=i) for i in range(31)} | {d for d in daily if d >= cutoff_30d})
        recent_series = np.array([daily.get(d, 0) for d in sorted(set(recent_days))])
        dod = float(np.mean(np.diff(recent_series.astype(float)))) if len(recent_series) > 1 else 0.0

        # Week-over-week (90d window)
        weekly = []
        for w in range(0, 90, 7):
            w_start = cutoff_90d + timedelta(days=w)
            w_end   = w_start + timedelta(days=7)
            weekly.append(sum(c for d, c in daily.items() if w_start <= d < w_end))
        wow = float(np.mean(np.diff(np.array(weekly, dtype=float)))) if len(weekly) > 1 else 0.0

        last_ts = max(ts for ts, _ in parsed)
        days_since = max(0.0, (now - last_ts).total_seconds() / 86400.0)

        total_count = len(parsed)
        weekend_count = sum(1 for ts, _ in parsed if ts.weekday() >= 5)
        weekend_ratio = weekend_count / max(total_count, 1)

        vec = np.array([[
            active_7d,
            active_30d,
            active_90d,
            utilisation_ratio,
            dod,
            wow,
            variance_daily,
            days_since,
            weekend_ratio,
        ]], dtype=float)

        return vec, FEATURE_COLUMNS

    # ── Scoring ────────────────────────────────────────────────────────────────

    def score(
        self,
        license_id: str,
        sso_events: list[dict],
        total_seats: int,
        now: Optional[datetime] = None,
    ) -> dict:
        """Score a single license and return anomaly_score + SHAP top_factors.

        Args:
            license_id: UUID string — used only for logging.
            sso_events: Raw SSO login events for this license (last 90 days).
            total_seats: Total licensed seats for the utilisation_ratio feature.
            now: Override the reference timestamp (useful in tests).

        Returns:
            {
                "anomaly_score": float,   # 0.0 (normal) – 1.0 (maximally anomalous)
                "model_version": str,
                "top_factors": [          # top N_TOP by |SHAP|; empty if SHAP unavailable
                    {"feature": str, "contribution": float},
                    ...
                ]
            }
        """
        if not self._load():
            # Model not trained yet — return a sentinel that won't trigger reclaim
            logger.warning(
                f"Anomaly scorer returning sentinel for {license_id}: model not loaded"
            )
            return {
                "anomaly_score": 0.0,
                "model_version": "not_trained",
                "top_factors": [],
            }

        bundle   = self.__class__._bundle
        model    = bundle["model"]
        features = bundle.get("features", [])
        s_min    = bundle.get("score_min", -0.5)
        s_max    = bundle.get("score_max", 0.0)
        version  = bundle.get("version", "unknown")

        # ── Feature vector ─────────────────────────────────────────────────
        X, feat_names = self._engineer(sso_events, total_seats, now=now)

        # Reorder columns to match training order if features were stored
        if features and features != feat_names:
            # Map by name — safety guard against column ordering drift
            col_map = {name: i for i, name in enumerate(feat_names)}
            try:
                X = np.array([[X[0, col_map[f]] for f in features]])
                feat_names = features
            except KeyError as e:
                logger.warning(f"Feature mismatch for {license_id}: {e}")

        # ── Anomaly score ──────────────────────────────────────────────────
        raw_score = float(model.score_samples(X)[0])
        span = s_max - s_min
        if span < 1e-9:
            anomaly_score = 0.0
        else:
            anomaly_score = float(np.clip((s_max - raw_score) / span, 0.0, 1.0))

        # ── SHAP attribution ───────────────────────────────────────────────
        top_factors: list[dict] = []
        explainer = self.__class__._shap_explainer
        if explainer is not None:
            try:
                shap_values = explainer.shap_values(X)  # shape (1, n_features)
                sv = shap_values[0]                      # (n_features,)
                top_indices = np.argsort(np.abs(sv))[::-1][:N_TOP]
                top_factors = [
                    {
                        "feature": feat_names[i],
                        "contribution": round(float(sv[i]), 6),
                    }
                    for i in top_indices
                    if abs(sv[i]) > 1e-9   # skip zero-contribution features
                ]
            except Exception as e:
                logger.warning(
                    f"SHAP attribution failed for license {license_id}: {e}",
                    exc_info=True,
                )

        logger.debug(
            f"License {license_id}: anomaly_score={anomaly_score:.4f} "
            f"top_factors={top_factors}"
        )

        return {
            "anomaly_score": round(anomaly_score, 6),
            "model_version": version,
            "top_factors": top_factors,
        }


# Module-level singleton — import and use directly in usage_service.py
_scorer_singleton = None
_scorer_lock = threading.Lock()


def get_scorer() -> UsageAnomalyScorer:
    """Return the process-level UsageAnomalyScorer singleton."""
    global _scorer_singleton
    if _scorer_singleton is None:
        with _scorer_lock:
            if _scorer_singleton is None:
                _scorer_singleton = UsageAnomalyScorer()
    return _scorer_singleton
