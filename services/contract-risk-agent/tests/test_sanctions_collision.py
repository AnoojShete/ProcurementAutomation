"""Tests for Prompt 11B: Sanctions false-positive collision bug & entity matching resolution.
Covers Rules A, B, C, D, and E.
"""
import pytest
from app.services import sanctions


def test_rule_a_short_token_guard():
    """Stems <= 3 chars must match exactly (==), else 0.0.
    Stems == 4 chars must match first char, else 0.0.
    """
    # 3-char stems:
    assert sanctions.calculate_similarity("TCS", "TCS") == 100.0
    assert sanctions.calculate_similarity("TCS", "MCS") == 0.0
    assert sanctions.calculate_similarity("IBM", "ICM") == 0.0
    assert sanctions.calculate_similarity("TCS", "RCS") == 0.0

    # 4-char stems:
    assert sanctions.calculate_similarity("BHEL", "BHEL") == 100.0
    assert sanctions.calculate_similarity("BHEL", "CHEL") == 0.0
    assert sanctions.calculate_similarity("ACME", "ECME") == 0.0
    # 4-char stems with matching initial letter:
    assert sanctions.calculate_similarity("BHEL", "BHEM") > 0.0


def test_rule_b_stopword_handling_and_stem_preservation():
    """DO NOT strip generic business fillers if doing so leaves a core stem <= 3 chars."""
    q_stem, q_clean = sanctions.extract_stems("Tcs Technologies Pvt Ltd")
    c_stem, c_clean = sanctions.extract_stems("MCS TECHNOLOGIES GMBH")

    assert q_stem == "tcs"
    assert c_stem == "mcs"
    assert q_clean == "tcs technologies"
    assert c_clean == "mcs technologies"

    # Crucial Prompt 11B test case:
    # "Tcs Technologies" must NOT match "MCS TECHNOLOGIES GMBH"
    sim = sanctions.calculate_similarity("Tcs Technologies", "MCS TECHNOLOGIES GMBH")
    assert sim == 0.0, f"Expected 0.0 due to short-token guard, got {sim}"


def test_rule_c_hybrid_scoring_metric():
    """Tests 0.6 * JaroWinkler + 0.4 * TokenSort composite score."""
    # Identical entities:
    assert sanctions.calculate_similarity("Acme Corporation", "Acme Inc") == 100.0

    # Prefix variation:
    score = sanctions.calculate_similarity("Tata Consultancy Services Limited", "Tata Consultancy Services")
    assert score == 100.0


def test_rule_d_secondary_attribute_disambiguation():
    """Tests Rule D country / jurisdiction gating logic."""
    # Score >= 95 with contradiction (IN vs DE) -> possible_match capped at 84
    status, score = sanctions.classify_sanctions_match(96.0, "IN", "DE")
    assert status == "possible_match"
    assert score == 84

    # Score >= 95 with country match -> match
    status, score = sanctions.classify_sanctions_match(96.0, "IN", "IN")
    assert status == "match"
    assert score == 96

    # Score >= 95 with unknown country -> match
    status, score = sanctions.classify_sanctions_match(96.0, "IN", "")
    assert status == "match"
    assert score == 96

    status, score = sanctions.classify_sanctions_match(96.0, "", "DE")
    assert status == "match"
    assert score == 96

    # Score between 80 and 94:
    # Matching country -> match
    status, score = sanctions.classify_sanctions_match(85.0, "IN", "IN")
    assert status == "match"
    assert score == 85

    # Mismatching or empty country -> possible_match
    status, score = sanctions.classify_sanctions_match(85.0, "IN", "DE")
    assert status == "possible_match"
    assert score == 85

    status, score = sanctions.classify_sanctions_match(85.0, "IN", "")
    assert status == "possible_match"
    assert score == 85

    # Score 70 to 79 -> possible_match
    status, score = sanctions.classify_sanctions_match(75.0, "IN", "DE")
    assert status == "possible_match"
    assert score == 75

    # Score < 70 -> no_match
    status, score = sanctions.classify_sanctions_match(68.0, "IN", "IN")
    assert status == "no_match"
    assert score == 68


def test_screen_name_with_direct_entries_iteration():
    """Verify screen_name does not false-positive on Tcs Technologies against MCS."""
    index = {
        "version": "v1",
        "entries": [
            {
                "id": "cand-mcs",
                "name": "MCS TECHNOLOGIES GMBH",
                "names": ["MCS TECHNOLOGIES GMBH", "MCS Technologies"],
                "countries": "de",
                "datasets": "OpenSanctions Consolidated",
            },
            {
                "id": "cand-genuine",
                "name": "Acme Supercorp Ltd",
                "names": ["Acme Supercorp Ltd", "Acme Supercorp"],
                "countries": "us",
                "datasets": "OFAC",
            }
        ]
    }

    # "Tcs Technologies" should have 0 hits against MCS TECHNOLOGIES GMBH
    hits = sanctions.screen_name("Tcs Technologies", index, cutoff=70.0)
    assert hits == []

    # "Acme Supercorp" should match cand-genuine
    hits_acme = sanctions.screen_name("Acme Supercorp", index, cutoff=70.0)
    assert len(hits_acme) == 1
    assert hits_acme[0]["entity_id"] == "cand-genuine"
    assert hits_acme[0]["score"] == 100.0
