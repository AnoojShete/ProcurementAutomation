"""Calibrated, risk-controlled document gate (research task RS-04).

Decides whether a document can skip review, with a statistical promise:
among the documents it accepts, the share that are wrong stays at or
below `alpha`, with probability at least 1 - `delta`.

  1. A calibrator turns a document's evidence (a feature vector) into
     p = P(the document is correct and safe to pay).
  2. Learn-then-Test (Angelopoulos et al., 2021) picks the threshold on
     p using a separate calibration set: for each candidate threshold it
     tests "the error rate among accepted documents is above alpha" with
     a binomial tail p-value, walking from the strictest threshold to the
     loosest (fixed-sequence testing) and stopping at the first one it
     can't reject. The loosest rejected threshold is used.
  3. A document is accepted when p >= threshold; otherwise it goes to
     review. If no threshold passes, nothing is accepted.

The candidate thresholds come from the *training* scores (so they don't
depend on the calibration set) and start at the coverage where a
rejection is possible at all: with n accepted documents and no errors,
the p-value is (1 - alpha)^n, so n must be at least log(delta)/log(1 - alpha)
(230 documents for alpha = 1 %, 114 for 2 %, 45 for 5 % at delta = 0.1).

Not used by the live pipeline yet: the current decision is the heuristic in
app/services/confidence.py. Wiring it in behind the business rule
`document.review_policy` is RS-11.
"""
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import binom
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CALIBRATORS = ("logistic", "hgb")


class _Constant:
    """Stand-in when the training labels are all one class (e.g. a field
    that was read right on every training document)."""

    def __init__(self, p: float):
        self.p = p

    def predict_proba(self, X):
        n = len(X)
        return np.column_stack([np.full(n, 1 - self.p), np.full(n, self.p)])


def make_calibrator(kind: str = "logistic", seed: int = 0):
    """logistic: interpretable weights a reviewer can read; hgb: histogram
    gradient boosting, for interactions between evidence."""
    if kind == "logistic":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=5000))
    if kind == "hgb":
        return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                              l2_regularization=1.0, random_state=seed)
    raise ValueError(f"unknown calibrator {kind!r}")


def fit_calibrator(X_train, y_train, kind: str = "logistic", seed: int = 0):
    y_train = np.asarray(y_train)
    if len(np.unique(y_train)) < 2:
        return _Constant(float(y_train[0]))
    return make_calibrator(kind, seed).fit(X_train, y_train)


def min_accepted(alpha: float, delta: float) -> int:
    """Fewest accepted documents for which zero errors rejects 'risk > alpha'."""
    return math.ceil(math.log(delta) / math.log(1 - alpha))


def binomial_p_value(errors: int, accepted: int, alpha: float) -> float:
    """P(at most `errors` wrong out of `accepted` | true error rate = alpha).
    Small means the error rate is very likely below alpha."""
    if accepted == 0:
        return 0.0  # accepting nothing can't be wrong
    return float(binom.cdf(errors, accepted, alpha))


def candidate_thresholds(train_scores: np.ndarray, n_cal: int, alpha: float, delta: float,
                         steps: int = 40) -> np.ndarray:
    """Strictest first. Coverage levels from the first one at which the
    calibration set could reject (with some slack) up to 100 %, turned into
    score thresholds with the training scores' quantiles."""
    start = min(1.0, 1.5 * min_accepted(alpha, delta) / max(n_cal, 1))
    coverages = np.linspace(start, 1.0, steps)
    return np.quantile(train_scores, 1.0 - coverages)


def ltt_threshold(cal_scores: np.ndarray, cal_wrong: np.ndarray, thresholds: np.ndarray,
                  alpha: float, delta: float) -> float:
    """Fixed-sequence Learn-then-Test. Returns the loosest threshold whose
    null 'error rate among accepted > alpha' is rejected at level delta,
    or +inf (accept nothing) if the strictest one already fails."""
    chosen = math.inf
    for t in thresholds:  # strictest first
        accepted = cal_scores >= t
        n = int(accepted.sum())
        k = int(cal_wrong[accepted].sum())
        if binomial_p_value(k, n, alpha) > delta:
            break
        chosen = float(t)
    return chosen


@dataclass
class Gate:
    calibrator: object
    threshold: float
    alpha: float
    delta: float

    @classmethod
    def fit(cls, X_train, y_train, X_cal, y_cal, alpha: float, delta: float = 0.1,
            kind: str = "logistic", seed: int = 0) -> "Gate":
        """y = 1 when the document is correct and safe to pay."""
        return cls.from_model(fit_calibrator(X_train, y_train, kind, seed), X_train, X_cal, y_cal, alpha, delta)

    @classmethod
    def from_model(cls, model, X_train, X_cal, y_cal, alpha: float, delta: float = 0.1) -> "Gate":
        """Only the threshold depends on alpha: reuse one fitted calibrator."""
        train_scores = model.predict_proba(X_train)[:, 1]
        cal_scores = model.predict_proba(X_cal)[:, 1]
        thresholds = candidate_thresholds(train_scores, len(y_cal), alpha, delta)
        t = ltt_threshold(cal_scores, 1 - np.asarray(y_cal), thresholds, alpha, delta)
        return cls(model, t, alpha, delta)

    def scores(self, X) -> np.ndarray:
        return self.calibrator.predict_proba(X)[:, 1]

    def accept(self, X) -> np.ndarray:
        return self.scores(X) >= self.threshold


def selective_metrics(accept: np.ndarray, wrong: np.ndarray, alpha: Optional[float] = None) -> dict:
    n_acc = int(accept.sum())
    errors = int(wrong[accept].sum())
    risk = errors / n_acc if n_acc else 0.0
    out = {"coverage": n_acc / len(accept), "accepted": n_acc, "errors": errors, "risk": risk}
    if alpha is not None:
        out["violation"] = risk > alpha
    return out


def aurc(scores: np.ndarray, wrong: np.ndarray) -> float:
    """Area under the risk-coverage curve (lower is better): the mean, over
    every coverage level, of the error rate among the top-scored documents."""
    order = np.argsort(-scores, kind="stable")
    cum_errors = np.cumsum(wrong[order])
    return float(np.mean(cum_errors / np.arange(1, len(order) + 1)))


def ece(scores: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (scores >= lo) & ((scores < hi) if hi < 1 else (scores <= hi))
        if m.any():
            total += m.mean() * abs(scores[m].mean() - correct[m].mean())
    return float(total)
