"""Deterministic Scorecard Evaluation Engine (Prompt 9B section 6 & 7).
Pure function, no I/O, `now` is an explicit parameter.
Given the same observations, same ruleset version, and same assessed_at,
produces byte-identical results.
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.services.scorecard.default_ruleset import canonical_json_hash
from app.services.scorecard.evaluator import (
    SafeEvaluator,
    format_date_human,
    render_template,
)

TIER_ORDER = {"low": 1, "moderate": 2, "high": 3, "critical": 4}
SPEND_TO_TIER = {"petty": "low", "standard": "moderate", "strategic": "high"}


def determine_band(points: int, bands: Dict[str, int]) -> str:
    """Computes band: Low (0 - low_max), Medium (low_max+1 - medium_max), High (above medium_max)."""
    low_max = bands.get("low_max", 24)
    medium_max = bands.get("medium_max", 49)
    if points <= low_max:
        return "Low"
    if points <= medium_max:
        return "Medium"
    return "High"


def calculate_effective_tier(
    spend_tier: Optional[str], inherent_tier: Optional[str]
) -> Tuple[str, List[Dict[str, str]]]:
    """Calculates effective_tier: stricter of inherent tier and spend tier mapped.
    Returns (effective_tier, provisional_reasons).
    """
    provisional_reasons = []
    mapped_spend = SPEND_TO_TIER.get((spend_tier or "").lower(), "moderate")

    if not inherent_tier:
        provisional_reasons.append({
            "code": "inherent_profile_missing",
            "signal": "inherent",
            "message": "Inherent risk profile is missing; falling back to spend tier.",
        })
        return mapped_spend, provisional_reasons

    inh = inherent_tier.lower()
    if inh not in TIER_ORDER:
        inh = "moderate"

    order_spend = TIER_ORDER.get(mapped_spend, 2)
    order_inh = TIER_ORDER.get(inh, 2)

    stricter = inh if order_inh >= order_spend else mapped_spend
    return stricter, provisional_reasons


def compute_ages_out_on(signal_key: str, fields: Dict[str, Any], rule_id: str, now: datetime) -> Optional[str]:
    """Computes the date an observation ages out or transitions to a safer rule."""
    if signal_key == "company_age":
        raw_date = fields.get("age.date")
        if raw_date:
            try:
                base_dt = datetime.strptime(str(raw_date)[:10], "%Y-%m-%d")
                # Thresholds are 1 year and 3 years
                y1 = date(base_dt.year + 1, base_dt.month, min(base_dt.day, 28))
                y3 = date(base_dt.year + 3, base_dt.month, min(base_dt.day, 28))
                today = now.date() if isinstance(now, datetime) else now
                if today < y1:
                    return y1.isoformat()
                if today < y3:
                    return y3.isoformat()
            except Exception:
                pass

    if signal_key == "breach":
        latest = fields.get("breach.latest_date")
        if latest:
            try:
                b_dt = datetime.strptime(str(latest)[:10], "%Y-%m-%d")
                y1 = date(b_dt.year + 1, b_dt.month, min(b_dt.day, 28))
                y5 = date(b_dt.year + 5, b_dt.month, min(b_dt.day, 28))
                today = now.date() if isinstance(now, datetime) else now
                if today < y1:
                    return y1.isoformat()
                if today < y5:
                    return y5.isoformat()
            except Exception:
                pass

    if signal_key == "incidents":
        latest = fields.get("inc.latest_date")
        if latest:
            try:
                i_dt = datetime.strptime(str(latest)[:10], "%Y-%m-%d")
                y2 = date(i_dt.year + 2, i_dt.month, min(i_dt.day, 28))
                return y2.isoformat()
            except Exception:
                pass

    return None


def evaluate_risk(
    ruleset: Dict[str, Any],
    observations: Dict[str, Any],  # signal_key -> observation dict or model
    assessed_at: datetime,
    vendor_context: Optional[Dict[str, Any]] = None,
    previous_score: Optional[Dict[str, Any]] = None,
    trigger_type: str = "manual",
    trigger_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure deterministic evaluation function.
    No I/O. Given identical inputs, returns identical dictionary output.
    """
    if assessed_at.tzinfo is None:
        assessed_at = assessed_at.replace(tzinfo=timezone.utc)

    vendor_context = vendor_context or {}
    spend_tier = vendor_context.get("spend_tier", "standard")
    inherent_tier = vendor_context.get("inherent_tier")
    vendor_name = vendor_context.get("name", "Vendor")

    effective_tier, tier_prov_reasons = calculate_effective_tier(spend_tier, inherent_tier)

    signals_def = ruleset.get("signals", [])
    bands_def = ruleset.get("bands", {"low_max": 24, "medium_max": 49})
    required_signals_map = ruleset.get("required_signals_by_tier", {})
    required_signals = set(required_signals_map.get(effective_tier, []))

    rule_results: List[Dict[str, Any]] = []
    override_rules: List[Dict[str, Any]] = []
    snapshot: Dict[str, Any] = {}
    observation_ids: List[str] = []
    provisional_reasons = list(tier_prov_reasons)

    total_points = 0
    unassessed_potential_points = 0
    due_diligence_potential_points = 0
    history_potential_points = 0

    if isinstance(observations, list):
        obs_map = {}
        for o in observations:
            k = getattr(o, "signal_key", None) or (o.get("signal_key") if isinstance(o, dict) else None)
            if k:
                obs_map[k] = o
        observations = obs_map

    for order_idx, sig_def in enumerate(signals_def):
        sig_key = sig_def["key"]
        group_key = sig_def.get("group", "identity")
        max_points = sig_def.get("max_points", 0)
        ttl_days = sig_def.get("ttl_days", 30)

        obs = observations.get(sig_key)
        is_fresh = False
        obs_fields = {}
        obs_facts = []
        obs_id = None
        raw_resp_id = None
        provider = "internal" if sig_key in ("delivery_sla", "feedback", "incidents") else "system"
        fetched_at_str = format_date_human(assessed_at)

        if obs:
            obs_status = getattr(obs, "status", None) or (obs.get("status") if isinstance(obs, dict) else "ok")
            # Handle both dict and ORM model
            o_fetched_at = getattr(obs, "fetched_at", None) or (obs.get("fetched_at") if isinstance(obs, dict) else None)
            if isinstance(o_fetched_at, str):
                try:
                    o_fetched_at = datetime.fromisoformat(o_fetched_at.replace("Z", "+00:00"))
                except ValueError:
                    o_fetched_at = None

            if o_fetched_at is None:
                o_fetched_at = assessed_at

            if o_fetched_at and obs_status not in ("not_assessed", "error", "not_checked"):
                if o_fetched_at.tzinfo is None:
                    o_fetched_at = o_fetched_at.replace(tzinfo=timezone.utc)
                age = (assessed_at - o_fetched_at).total_seconds()
                if age <= ttl_days * 86400:
                    is_fresh = True
                    fetched_at_str = format_date_human(o_fetched_at)

            if is_fresh:
                obs_fields = getattr(obs, "fields", None) or (obs.get("fields") if isinstance(obs, dict) else {}) or {}
                obs_facts = getattr(obs, "facts", None) or (obs.get("facts") if isinstance(obs, dict) else []) or []
                obs_id = str(getattr(obs, "id", None) or (obs.get("id") if isinstance(obs, dict) else "")) or None
                raw_resp_id = str(getattr(obs, "raw_response_id", None) or (obs.get("raw_response_id") if isinstance(obs, dict) else "")) or None
                provider = getattr(obs, "provider", None) or (obs.get("provider") if isinstance(obs, dict) else provider)
                if obs_id:
                    observation_ids.append(obs_id)

        if not is_fresh:
            # Synthetic observation for missing / expired signal
            last_checked_msg = "never checked"
            if obs:
                o_dt = getattr(obs, "fetched_at", None) or (obs.get("fetched_at") if isinstance(obs, dict) else None)
                if o_dt:
                    last_checked_msg = f"last checked {format_date_human(o_dt)}, older than {ttl_days} days"
            obs_fields = {}
            obs_facts = [
                {"label": "Source", "value": provider},
                {"label": "Retrieved", "value": assessed_at.strftime("%Y-%m-%d %H:%M:%S UTC")},
                {"label": "HTTP status", "value": "internal" if provider == "internal" else "not_checked"},
                {"label": "Status detail", "value": last_checked_msg},
            ]

        snapshot[sig_key] = obs_fields

        # Evaluate outcomes in order
        matched_outcome = None
        for outcome in sig_def.get("outcomes", []):
            when_cond = outcome.get("when")
            if SafeEvaluator.evaluate(when_cond, obs_fields):
                matched_outcome = outcome
                break

        if matched_outcome is None:
            # Fallback to last outcome
            matched_outcome = sig_def["outcomes"][-1]

        rule_id = matched_outcome["rule_id"]
        status = matched_outcome.get("status", "assessed")
        points = matched_outcome.get("points", 0)
        override_band = matched_outcome.get("override_band")
        rationale = matched_outcome.get("rationale", "")
        remediable = matched_outcome.get("remediable", True)

        kind = sig_def.get("kind", "due_diligence")
        coverage_type = sig_def.get("coverage_type", "full")

        # Potential points calculation (9C: detect_only signals never add potential points)
        if coverage_type == "detect_only":
            potential_points = 0
        elif status == "not_assessed":
            potential_points = max_points
        elif status == "review_pending":
            potential_points = max(0, max_points - points)
        else:
            potential_points = 0

        if kind == "history":
            history_potential_points += potential_points
        else:
            due_diligence_potential_points += potential_points

        # Render template context
        tmpl_context = dict(obs_fields)
        tmpl_context.update({
            "provider": provider,
            "fetched_at": fetched_at_str,
            "points": str(points),
            "vendor_name": vendor_name,
            "label": sig_def.get("label", sig_key),
            "country": vendor_context.get("country", "Unknown"),
            "domain": vendor_context.get("website_domain", "vendor domain"),
        })
        reason_text = render_template(matched_outcome.get("reason", ""), tmpl_context)

        # Render remediation actions
        remediation_actions = []
        for r_item in matched_outcome.get("remediation", []):
            r_copy = dict(r_item)
            r_copy["step"] = render_template(r_item.get("step", ""), tmpl_context)
            remediation_actions.append(r_copy)

        ages_out_on = compute_ages_out_on(sig_key, obs_fields, rule_id, assessed_at)

        rule_result = {
            "order_index": order_idx,
            "signal_key": sig_key,
            "group_key": group_key,
            "rule_id": rule_id,
            "status": status,
            "points": points,
            "potential_points": potential_points,
            "override_band": override_band,
            "observed_fields": obs_fields,
            "facts": obs_facts,
            "reason_text": reason_text,
            "rationale": rationale,
            "observation_id": obs_id,
            "raw_response_id": raw_resp_id,
            "remediation": remediation_actions,
            "remediable": remediable,
            "ages_out_on": ages_out_on,
            "max_points": max_points,
            "label": sig_def.get("label", sig_key),
            "remediation_target": matched_outcome.get("remediation_target", False),
            "kind": kind,
            "coverage_type": coverage_type,
        }
        rule_results.append(rule_result)

        total_points += points
        unassessed_potential_points += potential_points

        if override_band:
            override_rules.append({"rule_id": rule_id, "reason": reason_text})

        # Provisional requirement check (9C: satisfied ONLY when status is assessed or not_applicable)
        if sig_key in required_signals:
            if status not in ("assessed", "not_applicable"):
                provisional_reasons.append({
                    "code": f"required_signal_{status}",
                    "signal": sig_key,
                    "message": f"Required check '{sig_def.get('label', sig_key)}' is {status.replace('_', ' ')}.",
                })

    # Strict sum assertion invariant (non-negotiable Section 1.3)
    sum_calculated = sum(r["points"] for r in rule_results)
    assert total_points == sum_calculated, f"Invariant failed: total_points ({total_points}) != sum ({sum_calculated})"
    assert len(rule_results) == len(signals_def), "Every signal must appear exactly once"

    # Section B1: vendor.country required; if null -> country_unknown & vendor_country_missing
    vendor_country = vendor_context.get("country")
    if not vendor_country:
        provisional_reasons.append({
            "code": "vendor_country_missing",
            "signal": "gst",
            "message": "Vendor country of incorporation is missing.",
        })

    # Section C1 & User Correction 1: assessed_share_pct
    due_diligence_signals = [r for r in rule_results if r["kind"] == "due_diligence"]
    assessed_max = sum(r["max_points"] for r in due_diligence_signals if r["status"] == "assessed")
    applicable_dd_max = sum(
        r["max_points"]
        for r in due_diligence_signals
        if r["status"] != "not_applicable"
        and not (r["coverage_type"] == "detect_only" and r["status"] == "assessed_no_finding")
    )
    assessed_share_pct = int(100 * assessed_max // applicable_dd_max) if applicable_dd_max > 0 else 0

    min_share_pct = 50
    if ruleset.get("lookups") and "min_assessed_share_pct" in ruleset["lookups"]:
        min_share_pct = ruleset["lookups"]["min_assessed_share_pct"]
    elif "min_assessed_share_pct" in vendor_context:
        min_share_pct = vendor_context["min_assessed_share_pct"]

    if assessed_share_pct < min_share_pct:
        provisional_reasons.append({
            "code": "low_assessed_share",
            "signal": "coverage",
            "message": f"Assessed due diligence share ({assessed_share_pct}%) is below the {min_share_pct}% threshold.",
        })

    applicable_max_points = sum(r["max_points"] for r in rule_results if r["status"] != "not_applicable")

    # Rating status determination (Section C1)
    all_required_satisfied = True
    for r in rule_results:
        if r["signal_key"] in required_signals:
            if r["status"] not in ("assessed", "not_applicable"):
                all_required_satisfied = False
                break

    if assessed_share_pct == 0:
        rating_status = "not_rated"
    elif assessed_share_pct == 100 and all_required_satisfied:
        rating_status = "assessed"
    else:
        rating_status = "provisional"

    is_provisional = (rating_status == "provisional")
    worst_case_points = min(100, total_points + due_diligence_potential_points)
    points_band = determine_band(total_points, bands_def)
    worst_case_band = determine_band(worst_case_points, bands_def)
    points_is_lower_bound = (rating_status == "provisional")

    has_override = len(override_rules) > 0
    if has_override:
        final_band = "High"
    elif points_band in ("Medium", "High"):
        final_band = points_band
    else:
        final_band = "Low" if rating_status == "assessed" else "Unrated"

    blocked_by = [
        r["rule_id"] for r in rule_results if r.get("override_band")
    ]

    # Section 7.3 Headline selection (first match wins)
    if has_override:
        first_ov = override_rules[0]
        headline = (
            f"High rating (override): {first_ov['reason']} "
            f"The points total is {total_points}/100 ({points_band}), but rule {first_ov['rule_id']} forces High."
        )
    elif final_band == "Unrated":
        n_out = len([r for r in provisional_reasons if r.get("signal") != "inherent"])
        headline = f"Unrated - {total_points} points found so far, {n_out} required checks outstanding"
    elif is_provisional:
        outstanding_labels = ", ".join(f"'{r['signal']}'" for r in provisional_reasons if r.get("signal") != "inherent")
        n_out = len([r for r in provisional_reasons if r.get("signal") != "inherent"])
        headline = f"Provisional {final_band}: {total_points}/100. {n_out} required check(s) are outstanding: {outstanding_labels}."
    else:
        # Top 2 contributors
        assessed_contributors = [r for r in rule_results if r["points"] > 0]
        assessed_contributors.sort(key=lambda x: x["points"], reverse=True)
        top_str = ""
        if len(assessed_contributors) >= 2:
            top_str = f" Largest contributors: {assessed_contributors[0]['label']} (+{assessed_contributors[0]['points']}) and {assessed_contributors[1]['label']} (+{assessed_contributors[1]['points']})."
        elif len(assessed_contributors) == 1:
            top_str = f" Largest contributor: {assessed_contributors[0]['label']} (+{assessed_contributors[0]['points']})."

        unassessed_clause = ""
        na_count = sum(1 for r in rule_results if r["status"] == "not_assessed")
        if unassessed_potential_points > 0 and na_count > 0:
            unassessed_clause = f" {na_count} signal(s) not assessed could add up to {unassessed_potential_points} points, so the worst case is {worst_case_band}."

        headline = f"{final_band}: {total_points}/100.{top_str}{unassessed_clause}"

    # Section 7.4 Thought process generation
    thought_steps: List[Dict[str, Any]] = []
    groups_def = ruleset.get("groups", [])
    for g_idx, g in enumerate(groups_def, start=1):
        g_key = g["key"]
        g_label = g["label"]
        g_results = [r for r in rule_results if r["group_key"] == g_key]
        g_points = sum(r["points"] for r in g_results)
        g_max = sum(r["max_points"] for r in g_results)

        sig_checked = ", ".join(r["label"] for r in g_results)
        sentences = [r["reason_text"] for r in g_results if r["reason_text"]]
        narrative = f"Step {g_idx} {g_label}: we checked {sig_checked}. " + " ".join(sentences) + f" Subtotal {g_points}/{g_max}."
        thought_steps.append({
            "step": g_idx,
            "group_key": g_key,
            "group_label": g_label,
            "points": g_points,
            "max_points": g_max,
            "narrative": narrative,
        })

    # Arithmetic final step
    non_zero_signals = [f"{r['label']} ({r['points']})" for r in rule_results if r["points"] > 0]
    non_zero_str = " + ".join(non_zero_signals) if non_zero_signals else "0"
    override_sentence = f" Override rule {override_rules[0]['rule_id']} triggered, setting rating to High." if has_override else ""
    unassessed_sentence = f" {unassessed_potential_points} unassessed potential points remaining." if unassessed_potential_points > 0 else ""
    arithmetic_line = (
        f"Total = {non_zero_str} = {total_points}. Bands: Low 0-24, Medium 25-49, High 50+. "
        f"Result {points_band}.{override_sentence}{unassessed_sentence}"
    )
    thought_steps.append({
        "step": len(groups_def) + 1,
        "group_key": "total",
        "group_label": "Final Score Calculation",
        "points": total_points,
        "max_points": 100,
        "narrative": arithmetic_line,
    })

    # Section 7.6 Change since last
    change_since_last: Optional[Dict[str, Any]] = None
    if previous_score:
        prev_total = previous_score.get("total_points")
        prev_rules = {r.get("signal_key"): r for r in previous_score.get("rule_results", [])}
        changed_rules = []
        for r in rule_results:
            pr = prev_rules.get(r["signal_key"])
            if pr and pr.get("rule_id") != r["rule_id"]:
                pts_delta = r["points"] - pr.get("points", 0)
                reason_delta = "Observation value updated"
                if trigger_type == "ruleset_change":
                    reason_delta = "Ruleset version updated"
                elif trigger_type == "dispute_upheld":
                    reason_delta = f"Corrected after dispute #{trigger_ref or ''}"
                changed_rules.append({
                    "signal": r["signal_key"],
                    "from_rule": pr.get("rule_id"),
                    "to_rule": r["rule_id"],
                    "points_delta": pts_delta,
                    "reason_for_change": reason_delta,
                })
        change_since_last = {
            "previous_total": prev_total,
            "delta": (total_points - prev_total) if prev_total is not None else 0,
            "trigger": trigger_type,
            "changed_rules": changed_rules,
        }

    snapshot_hash = canonical_json_hash(snapshot)
    definition_hash = canonical_json_hash(ruleset)

    # Compile structured explanation payload (Section 7.1 & Prompt 9C)
    explanation = {
        "headline": headline,
        "final_band": final_band,
        "points_band": points_band,
        "rating_status": rating_status,
        "total_points": total_points,
        "max_points": 100,
        "applicable_max_points": applicable_max_points,
        "assessed_share_pct": assessed_share_pct,
        "due_diligence_potential_points": due_diligence_potential_points,
        "history_potential_points": history_potential_points,
        "points_is_lower_bound": points_is_lower_bound,
        "blocked_by": blocked_by,
        "override": {
            "applies": has_override,
            "rules": override_rules,
        },
        "range": {
            "worst_case_points": worst_case_points,
            "worst_case_band": worst_case_band,
            "unassessed_potential": due_diligence_potential_points,
            "due_diligence_potential": due_diligence_potential_points,
            "history_potential": history_potential_points,
        },
        "provisional": {
            "is_provisional": is_provisional,
            "reasons": provisional_reasons,
        },
        "effective_tier": effective_tier,
        "inherent": {
            "tier": inherent_tier,
            "spend_tier": spend_tier,
        },
        "groups": [
            {
                "key": g["key"],
                "label": g["label"],
                "points": sum(r["points"] for r in rule_results if r["group_key"] == g["key"]),
                "max_points": sum(r["max_points"] for r in rule_results if r["group_key"] == g["key"]),
            }
            for g in groups_def
        ],
        "signals": [
            {
                "signal_key": r["signal_key"],
                "label": r["label"],
                "group": r["group_key"],
                "status": r["status"],
                "points": r["points"],
                "max_points": r["max_points"],
                "rule_id": r["rule_id"],
                "reason_text": r["reason_text"],
                "rationale": r["rationale"],
                "facts": r["facts"],
                "kind": r.get("kind", "due_diligence"),
                "coverage_type": r.get("coverage_type", "full"),
                "source": {
                    "raw_response_id": r["raw_response_id"],
                    "observation_id": r["observation_id"],
                },
                "remediation": r["remediation"],
                "remediable": r["remediable"],
                "ages_out_on": r["ages_out_on"],
            }
            for r in rule_results
        ],
        "thought_process": thought_steps,
        "sum_check": {
            "sum_of_signal_points": total_points,
            "equals_total": True,
        },
        "change_since_last": change_since_last,
        "audit": {
            "assessed_at": assessed_at.isoformat(),
            "ruleset_version": ruleset.get("version", 2),
            "definition_hash": definition_hash,
            "snapshot_sha256": snapshot_hash,
            "observation_ids": observation_ids,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
        },
    }

    score_float = round(total_points / 100.0, 4) if rating_status != "not_rated" else None

    return {
        "total_points": total_points,
        "points_band": points_band,
        "final_band": final_band,
        "rating_status": rating_status,
        "risk_band": final_band,
        "risk_score": score_float,
        "applicable_max_points": applicable_max_points,
        "assessed_share_pct": assessed_share_pct,
        "due_diligence_potential_points": due_diligence_potential_points,
        "history_potential_points": history_potential_points,
        "points_is_lower_bound": points_is_lower_bound,
        "blocked_by": blocked_by,
        "override_rule_ids": [o["rule_id"] for o in override_rules],
        "unassessed_potential_points": due_diligence_potential_points,
        "worst_case_points": worst_case_points,
        "worst_case_band": worst_case_band,
        "is_provisional": is_provisional,
        "provisional_reasons": provisional_reasons,
        "effective_tier": effective_tier,
        "headline": headline,
        "explanation": explanation,
        "snapshot": snapshot,
        "snapshot_sha256": snapshot_hash,
        "assessed_at": assessed_at,
        "trigger_type": trigger_type,
        "trigger_ref": trigger_ref,
        "rule_results": rule_results,
        "observation_ids": observation_ids,
        "score_float": score_float,
    }
