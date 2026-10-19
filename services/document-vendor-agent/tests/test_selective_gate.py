"""RS-04: the risk-controlled gate and the procurement-world generator."""
import numpy as np

from app.services.gstin_service import validate_gstin_offline
from app.services.selective_gate import (
    Gate, aurc, binomial_p_value, candidate_thresholds, ltt_threshold, min_accepted, selective_metrics,
)
from scripts.procurement_world import INJECTION_RATES, build_world, render


def test_min_accepted_matches_the_binomial_bound():
    for alpha in (0.01, 0.02, 0.05):
        n = min_accepted(alpha, 0.1)
        assert binomial_p_value(0, n, alpha) <= 0.1 < binomial_p_value(0, n - 1, alpha)
    assert min_accepted(0.01, 0.1) == 230


def test_accepting_nothing_is_always_allowed():
    assert binomial_p_value(0, 0, 0.02) == 0.0
    scores = np.array([0.9, 0.8])
    assert ltt_threshold(scores, np.array([1, 1]), np.array([0.85, 0.5]), alpha=0.02, delta=0.1) == float("inf")


def _simulate(n, seed):
    """Two features; the document is correct with a probability that rises
    with the first one."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 2))
    p = 1 / (1 + np.exp(-(3 * X[:, 0] + 1.5)))
    y = (rng.random(n) < p).astype(int)
    return X, y


def test_gate_keeps_the_error_rate_among_accepted_below_alpha():
    alpha, delta, violations, coverages = 0.05, 0.1, 0, []
    for seed in range(40):
        X, y = _simulate(6000, seed)
        tr, ca, te = slice(0, 2000), slice(2000, 4000), slice(4000, 6000)
        gate = Gate.fit(X[tr], y[tr], X[ca], y[ca], alpha=alpha, delta=delta)
        m = selective_metrics(gate.accept(X[te]), 1 - y[te], alpha)
        violations += m["violation"]
        coverages.append(m["coverage"])
    assert violations / 40 <= delta + 0.05  # guarantee holds (with simulation slack)
    assert np.mean(coverages) > 0.3          # and the gate is not trivially rejecting everything


def test_candidate_thresholds_start_where_a_rejection_is_possible():
    scores = np.linspace(0, 1, 1001)
    t = candidate_thresholds(scores, n_cal=1000, alpha=0.02, delta=0.1)
    assert t[0] > t[-1]                                         # strictest first
    first_coverage = (scores >= t[0]).mean()
    assert first_coverage * 1000 >= min_accepted(0.02, 0.1)     # enough documents to reject


def test_aurc_prefers_a_score_that_ranks_errors_last():
    wrong = np.array([0, 0, 0, 1, 1])
    assert aurc(np.array([5, 4, 3, 2, 1]), wrong) < aurc(np.array([1, 2, 3, 4, 5]), wrong)


def test_world_is_deterministic_and_labelled():
    a, b = build_world(seed=3, n_vendors=12, n_invoices=150), build_world(seed=3, n_vendors=12, n_invoices=150)
    assert [d.document_number for d in a.documents] == [d.document_number for d in b.documents]
    assert all(validate_gstin_offline(v.gstin)[0] for v in a.vendors)
    assert {d.injection for d in a.documents} - {None} <= set(INJECTION_RATES)
    for d in a.documents:
        text = "\n".join(d.lines)
        assert d.document_number in text and f"{d.total:,.2f}" in text
        if d.injection == "duplicate":
            assert d.duplicate_of is not None
    data, name, ctype = render(a.documents[0], a.seed)
    assert data and name.startswith(a.documents[0].doc_id)
