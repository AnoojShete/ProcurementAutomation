"""Remediation engine and What-If sandbox (Prompt 9C Section G).
Calculates cumulative remediation path, override-clearing priority, fixed wording templates,
running recomputation of points and bands, blocked_by tracking, and would_be_cleared determination.
"""
import copy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from app.services.scorecard.engine import determine_band, evaluate_risk

DEFAULT_TEMPLATES = {
    "gstin_cancelled": "Provide evidence of GSTIN reactivation or a valid replacement GSTIN through the vendor portal.",
    "gstin_suspended": "Provide GST portal compliance acknowledgment showing suspension lifted.",
    "gstin_invalid": "Correct GSTIN on profile or submit registration certificate for manual validation.",
    "sanctions_match": "Non-remediable via standard workflow. Initiate a sanctions dispute if this is a false-positive identity match.",
    "bank_invalid": "Update bank account details in the portal and complete penny-drop verification.",
    "bank_change_pending": "Procurement or finance manager must verify payment change request through dual-control.",
    "cert_missing": "Upload a valid SOC 2 Type II or ISO 27001 certificate covering the contracted scope.",
    "adverse_media": "Submit a formal response or resolution evidence for the cited media reports.",
    "prohibited_jurisdiction": "Non-remediable via standard workflow. Sourcing from prohibited jurisdictions is barred by corporate policy.",
    "skipped_nonremediable_override": (
        "Not checked: a non-remediable block already applies; these checks run automatically "
        "if the block is lifted (e.g., if a false-positive match dispute is upheld)."
    ),
}

# Remediation target field presets
TARGET_FIELD_PRESETS = {
    "gst": {"gstin.status": "active", "gstin.verification_level": "live"},
    "sanctions": {"sanctions.status": "no_match", "sanctions.match_type": "none"},
    "bank": {"bank.status": "valid", "bank.change_pending": False},
    "web": {"web.reachable": True, "web.ssl_grade": "A", "web.cert_valid": True},
    "email": {"email.dmarc_policy": "reject", "email.spf_present": True},
    "breach": {"breach.remediation_accepted": True},
    "certification": {"cert.status": "valid"},
    "financial": {"fin.basis": "rating", "fin.rating_class": "investment", "fin.evidence_age_days": 30},
    "adverse_media": {"media.qualifying_articles": 0, "media.high_severity_count": 0},
}


def _get_action_template(
    ruleset: Dict[str, Any],
    signal_key: str,
    rule_id: str,
    skip_reason: Optional[str] = None,
    remediable: bool = True,
) -> str:
    """Retrieves fixed template wording from active ruleset lookups (Section G5, User Correction 3)."""
    templates = ruleset.get("remediation_templates") or DEFAULT_TEMPLATES

    if skip_reason == "skipped_nonremediable_override":
        return templates.get("skipped_nonremediable_override", DEFAULT_TEMPLATES["skipped_nonremediable_override"])

    if not remediable:
        if "SAN" in rule_id or signal_key == "sanctions":
            return templates.get("sanctions_match", DEFAULT_TEMPLATES["sanctions_match"])
        if "JUR" in rule_id or signal_key == "jurisdiction":
            return templates.get("prohibited_jurisdiction", DEFAULT_TEMPLATES["prohibited_jurisdiction"])
        return "Not remediable through procurement workflow. Requires executive risk acceptance (valid <= 30 days) or dispute resolution."

    # Remediable rules
    if signal_key == "gst":
        if "01" in rule_id:
            return templates.get("gstin_cancelled", DEFAULT_TEMPLATES["gstin_cancelled"])
        if "02" in rule_id:
            return templates.get("gstin_suspended", DEFAULT_TEMPLATES["gstin_suspended"])
        return templates.get("gstin_invalid", DEFAULT_TEMPLATES["gstin_invalid"])
    if signal_key == "bank":
        if "02" in rule_id:
            return templates.get("bank_change_pending", DEFAULT_TEMPLATES["bank_change_pending"])
        return templates.get("bank_invalid", DEFAULT_TEMPLATES["bank_invalid"])
    if signal_key == "certification":
        return templates.get("cert_missing", DEFAULT_TEMPLATES["cert_missing"])
    if signal_key == "adverse_media":
        return templates.get("adverse_media", DEFAULT_TEMPLATES["adverse_media"])
    if signal_key == "breach":
        return "Submit third-party security audit or incident closure report confirming remediation of past breaches."
    if signal_key == "web":
        return "Renew SSL certificate, ensure A/A+ TLS grade, and enable HSTS on corporate domain."
    if signal_key == "email":
        return "Configure valid SPF TXT record and set DMARC policy to p=reject on corporate email domain."
    if signal_key == "financial":
        return "Provide audited financial statements or CRISIL/ICRA investment-grade credit rating certificate."

    return "Resolve outstanding findings and provide supporting verification documents through vendor portal."


def build_remediation_plan(
    ruleset: Dict[str, Any],
    assessment: Dict[str, Any],
    observations: Dict[str, Any],
    assessed_at: datetime,
    audience: str = "internal",  # "internal" or "vendor"
    vendor_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generates the cumulative, override-aware remediation plan (Prompt 9C Section G).
    Step 1: clear the override (e.g. reactivate GSTIN).
    Step 2..N: resolve remaining findings ordered by points recoverable.
    """
    total_points = assessment.get("total_points", 0)
    rule_results = assessment.get("rule_results", [])
    effective_tier = assessment.get("effective_tier", "standard")
    v_ctx = vendor_context or {"spend_tier": effective_tier}

    # Signals catalogue in ruleset
    signals_by_key = {s["key"]: s for s in ruleset.get("signals", [])}

    # Identify findings that can or should be remediated
    findings: List[Dict[str, Any]] = []

    for res in rule_results:
        sig_key = res["signal_key"]
        sig_def = signals_by_key.get(sig_key, {})
        outcomes = sig_def.get("outcomes", [])
        target_outcome = next((o for o in outcomes if o.get("remediation_target")), None)
        target_points = target_outcome.get("points", 0) if target_outcome else 0

        current_points = res.get("points", 0)
        has_override = res.get("override_band") is not None
        is_remediable = res.get("remediable", True)
        status = res.get("status")

        # Skip if already satisfied at target and no override
        if not has_override and current_points <= target_points and status in ("assessed", "not_applicable", "assessed_no_finding"):
            continue

        points_recoverable = max(0, current_points - target_points)
        raw_obs = observations.get(sig_key, {})
        skip_reason = getattr(raw_obs, "skip_reason", None) if not isinstance(raw_obs, dict) else raw_obs.get("skip_reason")

        action_text = _get_action_template(
            ruleset=ruleset,
            signal_key=sig_key,
            rule_id=res["rule_id"],
            skip_reason=skip_reason,
            remediable=is_remediable,
        )

        findings.append({
            "signal_key": sig_key,
            "signal_label": res.get("label", sig_key.replace("_", " ").title()),
            "rule_id": res["rule_id"],
            "current_points": current_points,
            "target_points": target_points,
            "points_recoverable": points_recoverable,
            "potential_points": res.get("potential_points", 0),
            "override_band": res.get("override_band"),
            "has_override": has_override,
            "remediable": is_remediable,
            "action": action_text,
            "skip_reason": skip_reason,
            "raw_actions": res.get("remediation", []),
        })

    # Sort findings:
    # 1. Remediable overrides first (Step 1..k)
    # 2. Non-remediable overrides next (informative)
    # 3. Remaining remediable findings ordered by points_recoverable descending
    # 4. Remaining non-remediable findings
    def _finding_sort_key(item: Dict[str, Any]):
        if item["has_override"] and item["remediable"]:
            return (0, -item["points_recoverable"])
        if item["has_override"] and not item["remediable"]:
            return (1, -item["points_recoverable"])
        if item["remediable"]:
            return (2, -item["points_recoverable"])
        return (3, -item["points_recoverable"])

    findings.sort(key=_finding_sort_key)

    # Compute running cumulative remediation path
    running_obs = copy.deepcopy(observations)
    cumulative_steps: List[Dict[str, Any]] = []

    # Current state before any remediation step
    current_eval = evaluate_risk(ruleset, running_obs, assessed_at, vendor_context=v_ctx)
    curr_points = current_eval["total_points"]
    curr_band = current_eval["final_band"]

    step_idx = 1
    for f in findings:
        sig_key = f["signal_key"]
        pts_before = curr_points
        band_before = curr_band

        # If finding is remediable, simulate applying target fields
        if f["remediable"]:
            target_fields = TARGET_FIELD_PRESETS.get(sig_key, {})
            if sig_key not in running_obs or not running_obs[sig_key]:
                running_obs[sig_key] = {"fields": {}, "fetched_at": assessed_at, "provider": "remediation_target"}
            if isinstance(running_obs[sig_key], dict):
                running_obs[sig_key].setdefault("fields", {}).update(target_fields)
            else:
                # Mock observation object
                for k, v in target_fields.items():
                    running_obs[sig_key].fields[k] = v

        step_eval = evaluate_risk(ruleset, running_obs, assessed_at, vendor_context=v_ctx)
        pts_after = step_eval["total_points"]
        band_after = step_eval["final_band"]
        blocked_by = step_eval.get("blocked_by", [])
        rating_status = step_eval.get("rating_status", "not_rated")

        # Would be cleared if rating_status is assessed, no blocked_by, and band is Low/Medium
        would_be_cleared = (
            rating_status == "assessed"
            and len(blocked_by) == 0
            and band_after in ("Low", "Medium")
        )

        step_record = {
            "step": step_idx,
            "signal_key": sig_key,
            "signal_label": f["signal_label"],
            "rule_id": f["rule_id"],
            "action": f["action"],
            "points_before": pts_before,
            "points_after": pts_after,
            "points_recoverable": max(0, pts_before - pts_after),
            "band_before": band_before,
            "band_after": band_after,
            "blocked_by": blocked_by,
            "would_be_cleared": would_be_cleared,
            "remediable": f["remediable"],
        }
        cumulative_steps.append(step_record)

        curr_points = pts_after
        curr_band = band_after
        step_idx += 1

    # End state if all remediable actions done
    all_done_eval = current_eval if not findings else evaluate_risk(ruleset, running_obs, assessed_at, vendor_context=v_ctx)
    all_done_total = all_done_eval["total_points"]
    all_done_band = all_done_eval["final_band"]
    all_done_rating_status = all_done_eval.get("rating_status")
    all_done_blocked = all_done_eval.get("blocked_by", [])

    would_be_cleared_all = (
        all_done_rating_status == "assessed"
        and len(all_done_blocked) == 0
        and all_done_band in ("Low", "Medium")
    )

    summary_sentence = (
        f"Completing all remediable items would change score from {total_points} ({assessment.get('final_band')}) "
        f"to {all_done_total} ({all_done_band})."
    )

    # Group actions by 'who'
    grouped_by_who: Dict[str, List[Dict[str, Any]]] = {}
    for step in cumulative_steps:
        who = "vendor" if audience == "vendor" else "procurement"
        grouped_by_who.setdefault(who, []).append({
            "step": step["step"],
            "signal_label": step["signal_label"],
            "action": step["action"],
            "points_recoverable": step["points_recoverable"],
            "remediable": step["remediable"],
            "would_be_cleared": step["would_be_cleared"],
        })

    return {
        "audience": audience,
        "current_total": total_points,
        "current_band": assessment.get("final_band"),
        "current_rating_status": assessment.get("rating_status"),
        "current_blocked_by": assessment.get("blocked_by", []),
        "new_total_if_all_done": all_done_total,
        "new_band_if_all_done": all_done_band,
        "new_rating_status_if_all_done": all_done_rating_status,
        "would_be_cleared_if_all_done": would_be_cleared_all,
        "summary": summary_sentence,
        "steps": cumulative_steps,
        "items": findings,
        "grouped_by_who": grouped_by_who,
    }


def simulate_what_if(
    ruleset: Dict[str, Any],
    base_observations: Dict[str, Any],
    field_overrides: Dict[str, Any],
    assessed_at: datetime,
    vendor_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """What-if simulation accepting hypothetical field values and returning full pure assessment (Section G3).
    Guarantees: pure in-memory evaluation; never writes to risk_scores or audit_log;
    never fires events; never calls external APIs.
    """
    sim_obs = copy.deepcopy(base_observations)

    from app.services.scorecard.field_catalogue import SIGNAL_FIELD_CATALOGUE

    for field_name, value in field_overrides.items():
        # Find which signal owns this field
        target_signal = None
        for s_key, s_fields in SIGNAL_FIELD_CATALOGUE.items():
            if field_name in s_fields:
                target_signal = s_key
                break

        if not target_signal:
            target_signal = field_name.split(".")[0] if "." in field_name else "custom"

        if target_signal not in sim_obs or not sim_obs[target_signal]:
            sim_obs[target_signal] = {
                "fields": {},
                "fetched_at": assessed_at,
                "provider": "what_if_simulation",
            }

        if isinstance(sim_obs[target_signal], dict):
            sim_obs[target_signal].setdefault("fields", {})[field_name] = value
        else:
            sim_obs[target_signal].fields[field_name] = value

    res = evaluate_risk(ruleset, sim_obs, assessed_at, vendor_context=vendor_context)

    # Determine clearance for tiers
    cleared_by_tier = {}
    for tier in ("low", "moderate", "high", "critical"):
        # Clearance requires rating_status == 'assessed', no blocked_by, and acceptable band
        # High/Critical tiers require Low band, low/moderate allows Low/Medium
        max_allowed_band = ("Low", "Medium") if tier in ("low", "moderate") else ("Low",)
        is_cleared = (
            res.get("rating_status") == "assessed"
            and len(res.get("blocked_by", [])) == 0
            and res.get("final_band") in max_allowed_band
        )
        cleared_by_tier[tier] = is_cleared

    return {
        "simulated_score": res.get("risk_score"),
        "total_points": res.get("total_points"),
        "final_band": res.get("final_band"),
        "points_band": res.get("points_band"),
        "rating_status": res.get("rating_status"),
        "blocked_by": res.get("blocked_by", []),
        "cleared_by_tier": cleared_by_tier,
        "rule_results": res.get("rule_results", []),
    }
