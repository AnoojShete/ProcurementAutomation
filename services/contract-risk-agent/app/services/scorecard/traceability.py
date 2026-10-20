"""Traceability, replay verification and audit bundle packaging (Prompt 9B section 9).
"""
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.services.scorecard.default_ruleset import canonical_json_hash
from app.services.scorecard.engine import evaluate_risk


def replay_assessment(
    stored_score: Dict[str, Any],
    ruleset_definition: Dict[str, Any],
) -> Dict[str, Any]:
    """Replays assessment using stored snapshot and stored ruleset definition.
    Asserts determinism: evaluates again and returns match details or field differences.
    """
    snapshot = stored_score.get("snapshot") or {}
    assessed_at = stored_score.get("assessed_at")
    if isinstance(assessed_at, str):
        assessed_at = datetime.fromisoformat(assessed_at.replace("Z", "+00:00"))
    elif not isinstance(assessed_at, datetime):
        assessed_at = datetime.now(timezone.utc)

    # Convert snapshot into synthetic observations for evaluation
    reconstituted_obs: Dict[str, Any] = {}
    for sig_key, sig_fields in snapshot.items():
        reconstituted_obs[sig_key] = {
            "fields": sig_fields,
            "fetched_at": assessed_at,
            "provider": "snapshot_replay",
        }

    replayed = evaluate_risk(
        ruleset=ruleset_definition,
        observations=reconstituted_obs,
        assessed_at=assessed_at,
        vendor_context={"spend_tier": stored_score.get("effective_tier")},
        trigger_type=stored_score.get("trigger_type", "replay"),
        trigger_ref=stored_score.get("trigger_ref"),
    )

    # Compare replay output with stored values
    differences = []
    if replayed["total_points"] != stored_score.get("total_points"):
        differences.append({
            "field": "total_points",
            "stored": stored_score.get("total_points"),
            "replayed": replayed["total_points"],
        })
    if replayed["final_band"] != stored_score.get("final_band"):
        differences.append({
            "field": "final_band",
            "stored": stored_score.get("final_band"),
            "replayed": replayed["final_band"],
        })
    if replayed["snapshot_sha256"] != stored_score.get("snapshot_sha256"):
        differences.append({
            "field": "snapshot_sha256",
            "stored": stored_score.get("snapshot_sha256"),
            "replayed": replayed["snapshot_sha256"],
        })

    is_equal = len(differences) == 0

    return {
        "equal": is_equal,
        "score_id": str(stored_score.get("id")),
        "vendor_id": str(stored_score.get("vendor_id")),
        "stored_snapshot_sha256": stored_score.get("snapshot_sha256"),
        "replayed_snapshot_sha256": replayed["snapshot_sha256"],
        "ruleset_definition_hash": canonical_json_hash(ruleset_definition),
        "differences": differences,
        "replayed_total_points": replayed["total_points"],
        "replayed_final_band": replayed["final_band"],
    }


def compile_audit_bundle(
    score_row: Dict[str, Any],
    rule_results: List[Dict[str, Any]],
    observations: List[Dict[str, Any]],
    raw_responses: List[Dict[str, Any]],
    ruleset: Dict[str, Any],
) -> Dict[str, Any]:
    """Compiles single audit bundle JSON containing full provenance of an assessment (Section 9.2)."""
    raw_summary = []
    for raw in raw_responses:
        raw_summary.append({
            "id": str(raw.get("id")),
            "signal_key": raw.get("signal_key"),
            "provider": raw.get("provider"),
            "request_method": raw.get("request_method"),
            "request_url_redacted": raw.get("request_url_redacted"),
            "response_status": raw.get("response_status"),
            "body_sha256": raw.get("body_sha256"),
            "body_bytes": raw.get("body_bytes"),
            "fetched_at": raw.get("fetched_at").isoformat() if isinstance(raw.get("fetched_at"), datetime) else raw.get("fetched_at"),
            "retention_until": str(raw.get("retention_until")),
            "body_purged": (raw.get("body_text") is None and raw.get("body_object_key") is None),
        })

    return {
        "score": score_row,
        "rule_results": rule_results,
        "observations": observations,
        "raw_responses": raw_summary,
        "ruleset": {
            "version": ruleset.get("version"),
            "definition": ruleset.get("definition", ruleset),
            "definition_hash": ruleset.get("definition_hash", canonical_json_hash(ruleset.get("definition", ruleset))),
        },
        "snapshot": score_row.get("snapshot"),
        "snapshot_sha256": score_row.get("snapshot_sha256"),
        "bundle_generated_at": datetime.now(timezone.utc).isoformat(),
    }
