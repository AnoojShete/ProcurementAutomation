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

TIER_ORDER = {"low": 0, "moderate": 1, "high": 2, "critical": 3}
SPEND_TO_TIER = {
    "petty": "low",
    "standard": "moderate",
    "strategic": "high",
    "low": "low",
    "moderate": "moderate",
    "high": "high",
    "critical": "critical",
}


# A check that can't run for lack of information about the vendor (owner,
# 30 Oct 2026, revised the same evening). When the gap is in our records
# (nobody entered the GSTIN, country, website...) the vendor is charged about a
# third of the check and the buyer is asked for the data; the rating stays
# provisional, so it is never cleared on the reduced charge. Bank details are
# collected before the first payment, so their absence costs nothing earlier.
# When the vendor's own side is the problem (its mail domain has no MX) the
# check counts in full. A check that never ran, ran with live mode off, or hit
# a provider error is our side and is re-weighted out instead; so are news,
# breaches and order history (nobody could know yet).
NOT_ENTERED_SHARE = {"bank": 0.0}
DEFAULT_NOT_ENTERED_SHARE = 1 / 3

COUNTRY_NEEDED = ("country", "Country not entered. Add the vendor's country so the GST and jurisdiction checks can run.")
DATA_NEEDED = {
    "gst": ("gstin", "GSTIN not entered. Add it on the vendor page, or confirm the vendor has no GSTIN "
                     "(below the registration threshold)."),
    "jurisdiction": COUNTRY_NEEDED,
    "company_age": ("registration_date", "No registration or incorporation date on record. It comes from a "
                                         "verified GSTIN or the company registry."),
    "financial": ("financials", "No financial statements or credit rating on file. Upload recent financials."),
    "bank": ("bank_details", "Bank details not entered. Needed before the first payment."),
    "web": ("website", "Website not entered."),
    "email": ("contact_email", "Contact email not entered."),
}


def data_gap(sig_key: str, status: str, fields: Dict[str, Any]) -> Optional[str]:
    """Why a check couldn't be completed for lack of vendor information:
    "not_entered" (missing from our records), "vendor" (the vendor's own
    side), or None (not a vendor-information gap)."""
    if not fields or status == "assessed":
        return None
    if sig_key == "gst":
        return "not_entered" if fields.get("gstin.verification_level") in ("country_unknown", "pending") else None
    if sig_key == "jurisdiction":
        return "not_entered" if status == "not_assessed" and fields.get("country.code") == "UNKNOWN" else None
    if sig_key == "company_age":
        return "not_entered" if status == "not_assessed" and fields.get("age.basis") in ("none", "domain_only") else None
    if sig_key == "financial":
        return "not_entered" if status == "not_assessed" and fields.get("fin.basis") == "none" else None
    if sig_key == "bank":
        return "not_entered" if fields.get("na_reason_code") == "no_bank_details" else None
    if sig_key == "web":
        return "not_entered" if fields.get("na_reason_code") == "no_domain" else None
    if sig_key == "email":
        if fields.get("na_reason_code") == "no_email_domain":
            return "not_entered"
        if fields.get("email.confidence") == "live" and fields.get("email.has_mx") is False:
            return "vendor"
    return None


def gap_charge(sig_key: str, gap: Optional[str], max_points: int, points: int) -> int:
    """Points a data gap adds on top of the check's own points."""
    if gap == "vendor":
        return max_points - points
    if gap == "not_entered":
        return round(max_points * NOT_ENTERED_SHARE.get(sig_key, DEFAULT_NOT_ENTERED_SHARE))
    return 0


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
    """Calculates effective_tier = max(inherent_tier, spend_tier) using strictness rank:
    low (0) < moderate (1) < high (2) < critical (3).
    Only flags inherent_profile_missing if vendor.inherent_tier is None.
    Returns (effective_tier, provisional_reasons).
    """
    provisional_reasons = []
    raw_spend = (spend_tier or "").lower()
    mapped_spend = SPEND_TO_TIER.get(raw_spend, "moderate")

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

    order_spend = TIER_ORDER.get(mapped_spend, 1)
    order_inh = TIER_ORDER.get(inh, 1)

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

            if o_fetched_at:
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

        # Potential points calculation (9C: detect_only signals never add potential points, except review_pending per Prompt 11 Section 1.3)
        if status == "review_pending":
            potential_points = max(0, max_points - points)
        elif coverage_type == "detect_only":
            potential_points = 0
        elif status == "not_assessed":
            potential_points = max_points
        else:
            potential_points = 0

        if kind == "history":
            history_potential_points += potential_points
        else:
            due_diligence_potential_points += potential_points

        # Render template context
        tmpl_context = dict(obs_fields)
        tier_val = vendor_context.get("tier") or vendor_context.get("inherent_tier") or vendor_context.get("spend_tier") or "standard"
        tmpl_context.update({
            "provider": provider,
            "fetched_at": fetched_at_str,
            "points": str(points),
            "vendor_name": vendor_name,
            "label": sig_def.get("label", sig_key),
            "country": vendor_context.get("country", "Unknown"),
            "domain": vendor_context.get("website_domain", "vendor domain"),
            "vendor.tier": tier_val,
            "vendor.country": vendor_context.get("country", "Unknown"),
        })
        reason_text = render_template(matched_outcome.get("reason", ""), tmpl_context)
        if not reason_text or reason_text.strip() == "—" or reason_text.strip() == "":
            reason_text = "(not recorded)"
        elif "—" in reason_text and reason_text.strip().endswith("—."):
            reason_text = reason_text.replace("—.", "(not recorded).")

        na_reason_code = matched_outcome.get("na_reason_code") or obs_fields.get("na_reason_code")

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
            "na_reason_code": na_reason_code,
        }
        rule_results.append(rule_result)

        total_points += points
        unassessed_potential_points += potential_points

        if override_band:
            override_rules.append({"rule_id": rule_id, "reason": reason_text})

        # Provisional requirement check (Prompt 11 Section 2.4, 3.5: GST requires exact/confirmed; not_applicable requires na_reason_code)
        if sig_key in required_signals:
            satisfied = False
            if sig_key == "gst":
                match_level = obs_fields.get("gstin.name_match_level")
                if status == "assessed" and match_level in ("exact", "confirmed"):
                    satisfied = True
                elif status == "not_applicable" and na_reason_code:
                    satisfied = True
            else:
                if status == "assessed":
                    satisfied = True
                elif status == "not_applicable" and na_reason_code:
                    satisfied = True
            if not satisfied:
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
    # Detect-only checks (news, breach) can only find problems, never confirm
    # their absence, so one that found nothing or couldn't run doesn't count
    # against coverage; its weight goes to the checks that ran (below).
    applicable_dd_max = sum(
        r["max_points"]
        for r in due_diligence_signals
        if r["status"] != "not_applicable"
        and not (r["coverage_type"] == "detect_only" and r["status"] in ("assessed_no_finding", "not_assessed"))
    )
    assessed_share_pct = int(100 * assessed_max // applicable_dd_max) if applicable_dd_max > 0 else 0

    # Every applicable due-diligence check must be in before a rating is
    # "assessed" (red team: missing data is never shown as Low).
    min_share_pct = 100
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

    # Rating status determination (Prompt 11 Section 2.4, 3.5 & Mandatory Fix 3)
    all_required_satisfied = True
    for r in rule_results:
        if r["signal_key"] in required_signals:
            sk = r["signal_key"]
            st = r["status"]
            na_code = r.get("na_reason_code")
            if sk == "gst":
                ml = r.get("observed_fields", {}).get("gstin.name_match_level")
                if not ((st == "assessed" and ml in ("exact", "confirmed")) or (st == "not_applicable" and na_code)):
                    all_required_satisfied = False
                    break
            else:
                if not (st == "assessed" or (st == "not_applicable" and na_code)):
                    all_required_satisfied = False
                    break

    # Data gaps are charged (see gap_charge) and listed for the buyer; without
    # a verified GSTIN or registration date the vendor can't be rated "assessed".
    data_needed: List[Dict[str, Any]] = []
    for r in rule_results:
        r["data_gap"] = data_gap(r["signal_key"], r["status"], r.get("observed_fields") or {})
        r["unverified"] = r["data_gap"] is not None
        r["gap_points"] = gap_charge(r["signal_key"], r["data_gap"], r["max_points"], r["points"])
        if r["data_gap"] == "not_entered" and r["signal_key"] in DATA_NEEDED:
            field, message = DATA_NEEDED[r["signal_key"]]
            if r["signal_key"] == "gst" and (r.get("observed_fields") or {}).get("gstin.verification_level") == "country_unknown":
                field, message = COUNTRY_NEEDED
            if not any(d["field"] == field for d in data_needed):
                data_needed.append({"field": field, "signal": r["signal_key"], "message": message,
                                    "points": r["gap_points"]})
            else:
                next(d for d in data_needed if d["field"] == field)["points"] += r["gap_points"]
    by_key = {r["signal_key"]: r for r in rule_results}
    gst_r, age_r = by_key.get("gst", {}), by_key.get("company_age", {})
    gst_fields = gst_r.get("observed_fields") or {}
    gst_verified = gst_r.get("status") == "assessed" and gst_fields.get("gstin.name_match_level") in ("exact", "confirmed")
    registered = (age_r.get("status") == "assessed"
                  and (age_r.get("observed_fields") or {}).get("age.basis") in ("incorporation", "gst_registration"))
    identity_verified = gst_verified or registered
    if not identity_verified and any(r.get("observed_fields") for r in rule_results):
        provisional_reasons.append({
            "code": "identity_unverified", "signal": "identity",
            "message": "No verified GSTIN or registration date: the vendor's identity can't be confirmed.",
        })

    # A missing inherent profile only falls back to the spend tier (advisory,
    # like the headline count below); every other reason keeps it provisional.
    blocking_reasons = [r for r in provisional_reasons if r.get("signal") != "inherent"]
    # "not_rated" only when no check returned anything; a vendor whose checks
    # ran but are waiting for data is provisional.
    if assessed_share_pct == 0 and not any(r.get("observed_fields") for r in rule_results):
        rating_status = "not_rated"
    elif assessed_share_pct >= min_share_pct and all_required_satisfied and vendor_country and not blocking_reasons:
        rating_status = "assessed"
    else:
        rating_status = "provisional"

    is_provisional = (rating_status == "provisional")
    worst_case_points = min(100, total_points + due_diligence_potential_points)
    worst_case_band = determine_band(worst_case_points, bands_def)
    points_is_lower_bound = (rating_status == "provisional")

    # Every vendor gets a band (owner decision, 30 Oct 2026): a check that
    # couldn't run is left out and the others are scaled back up to 100, so
    # 7 points over the 57 points that were checked score 12/100. With no
    # check done at all the worst case applies (High) until one is. Clearance
    # still reads rating_status, so a provisional vendor is banded, not cleared.
    all_max_points = sum(r["max_points"] for r in rule_results)
    unverified = [r for r in rule_results if r["unverified"]]
    unverified_points = sum(r["gap_points"] for r in unverified)
    missing_max_points = sum(r["max_points"] for r in rule_results
                             if r["status"] == "not_assessed" and not r["unverified"])
    checked_max_points = all_max_points - missing_max_points
    if checked_max_points > 0:
        weighted_points = min(100, round((total_points + unverified_points) * all_max_points / checked_max_points))
    else:
        weighted_points = 100
    points_band = determine_band(weighted_points, bands_def)
    # Forced High only when the GST check ran and found a problem (name or PAN
    # mismatch); identity that is merely not entered yet is banded from its
    # points and stays provisional until it is.
    identity_floor = not identity_verified and gst_r.get("status") == "review_pending"

    has_override = len(override_rules) > 0
    final_band = "High" if (has_override or identity_floor) else points_band

    blocked_by = [
        {
            "rule_id": r["rule_id"],
            "short_label": r["label"],
            "remediable": r.get("remediable", True),
        }
        for r in rule_results if r.get("override_band")
    ]

    # Section 7.3 Headline selection (first match wins)
    if has_override:
        first_ov = override_rules[0]
        headline = (
            f"High rating (override): {first_ov['reason']} "
            f"The points total is {total_points}/100 ({points_band}), but rule {first_ov['rule_id']} forces High."
        )
    elif checked_max_points == 0:
        headline = "High until checked: no risk check has completed yet, so the worst case applies."
    elif identity_floor:
        headline = (f"Provisional High: the GSTIN on record doesn't match the vendor, so its identity can't be "
                    f"verified and it is treated as high risk until it is. Score {weighted_points}/100.")
    elif is_provisional:
        labels = {r["signal_key"]: r["label"] for r in rule_results}
        labels["coverage"] = "the remaining due-diligence checks"
        labels["identity"] = "identity (GSTIN or registration)"
        outstanding = list(dict.fromkeys(labels.get(r["signal"], r["signal"])
                                         for r in provisional_reasons if r.get("signal") != "inherent"))
        charged = (f" incl. {unverified_points} for missing information"
                   if unverified_points else "")
        if data_needed:
            outstanding = [("GSTIN" if d["field"] == "gstin" else d["field"].replace("_", " ")) for d in data_needed
                           if d["field"] != "bank_details"] + [
                o for o in outstanding if o != labels["identity"]]
        headline = (f"Provisional {final_band}: {weighted_points}/100 ({total_points + unverified_points} points{charged} "
                    f"over the {checked_max_points} points checked). Not cleared until these are done: {', '.join(outstanding)}.")
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

        charged = (f" {unverified_points} of them for missing information ("
                   f"{', '.join(r['label'] for r in unverified)})." if unverified_points else "")
        weighting = (f" Weighted from {total_points + unverified_points} points over the {checked_max_points} points checked "
                     f"({missing_max_points} points of checks couldn't run).{charged}" if missing_max_points or unverified_points else "")
        headline = f"{final_band}: {weighted_points}/100.{weighting}{top_str}{unassessed_clause}"

    # Section 7.4 Thought process generation (Prompt 11 Section 3.1, 3.3, 3.4)
    thought_steps: List[Dict[str, Any]] = []
    groups_def = ruleset.get("groups", [])
    for g_idx, g in enumerate(groups_def, start=1):
        g_key = g["key"]
        g_label = g["label"]
        g_results = [r for r in rule_results if r["group_key"] == g_key]
        g_points = sum(r["points"] for r in g_results)
        g_max = sum(r["max_points"] for r in g_results)
        g_potential = sum(r["potential_points"] for r in g_results)

        applicable = len([r for r in g_results if r["status"] != "not_applicable"])
        completed = len([r for r in g_results if r["status"] in ("assessed", "assessed_no_finding", "not_applicable")])

        header = f"{g_label}: {g_points} points found, {completed} of {applicable} checks completed, up to {g_potential} points still possible"
        signal_lines = [f"{r['label']}: {r['reason_text']}" for r in g_results if r["reason_text"]]
        narrative = header + ("\n" + "\n".join(signal_lines) if signal_lines else "")
        thought_steps.append({
            "step": g_idx,
            "group_key": g_key,
            "group_label": g_label,
            "points": g_points,
            "max_points": g_max,
            "potential_points": g_potential,
            "checks_completed": completed,
            "checks_applicable": applicable,
            "narrative": narrative,
        })

    # Arithmetic final step (Prompt 11 Section 3.4)
    non_zero_signals = [f"{r['label']} (+{r['points']})" for r in rule_results if r["points"] > 0]
    done_req = sum(1 for r in rule_results if r["signal_key"] in required_signals and (r["status"] == "assessed" or (r["status"] == "not_applicable" and r.get("na_reason_code"))))
    total_req = len(required_signals)

    if not non_zero_signals:
        assessed_nf = [r["label"] for r in rule_results if r["status"] == "assessed_no_finding"]
        not_assessed_lbls = [r["label"] for r in rule_results if r["status"] == "not_assessed"]
        arithmetic_line = (
            f"Total points found: 0 of 100. No signal added points. "
            f"Assessed with no finding: {', '.join(assessed_nf) if assessed_nf else 'none'}. "
            f"Not assessed: {', '.join(not_assessed_lbls) if not_assessed_lbls else 'none'}."
        )
    else:
        arithmetic_line = f"Total points found: {total_points} of 100. Breakdown: {', '.join(non_zero_signals)}."

    if rating_status != "assessed":
        arithmetic_line += (
            f" This is not a safe score: {done_req} of {total_req} required checks are complete "
            f"and up to {due_diligence_potential_points} points are still possible."
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

    # Build Prompt 11 honest groups with headers and short_label prefixed sentences
    groups_output = []
    for g in groups_def:
        g_results = [r for r in rule_results if r["group_key"] == g["key"]]
        g_app = [r for r in g_results if r["status"] != "not_applicable"]
        g_done = [r for r in g_results if r["status"] in ("assessed", "assessed_no_finding")]
        checks_completed = len(g_done)
        applicable_checks = len(g_app)
        potential = sum(r.get("potential_points", 0) for r in g_results)
        if potential > 0:
            hdr = f"{checks_completed} of {applicable_checks} checks completed; up to {potential} points may be added"
        else:
            hdr = f"{checks_completed} of {applicable_checks} checks completed"

        sentences = [f"{r['label']}: {r['reason_text']}" for r in g_results]
        groups_output.append({
            "key": g["key"],
            "label": g["label"],
            "points": sum(r["points"] for r in g_results),
            "max_points": sum(r["max_points"] for r in g_results),
            "header": hdr,
            "sentences": sentences,
        })

    # Arithmetic line and safety notice (Prompt 11 Section 3)
    if due_diligence_potential_points > 0:
        arithmetic_line = f"Total = {total_points} assessed + {due_diligence_potential_points} potential points = {total_points + due_diligence_potential_points} maximum"
    elif total_points == 0:
        arithmetic_line = "Total = 0 points"
    else:
        arithmetic_line = f"Total = {total_points} points"

    unassessed_req = [p["message"] for p in provisional_reasons if p.get("code", "").startswith("required_signal_")]
    if unassessed_req:
        safety_notice = "Required checks incomplete: " + "; ".join(unassessed_req) + " must be completed before rating is final."
    else:
        safety_notice = None

    # Compile structured explanation payload (Section 7.1 & Prompt 9C)
    score_breakdown = [
        {
            "rule_id": r["rule_id"],
            "signal_key": r["signal_key"],
            "signal_label": r.get("label") or r["signal_key"],
            "label": r.get("label") or r["signal_key"],
            "group_key": r["group_key"],
            "group": r["group_key"],
            "status": r["status"],
            "points": r["points"],
            "potential_points": r.get("potential_points", r.get("max_points", r["points"])),
            "max_points": r.get("max_points", r.get("potential_points", r["points"])),
            "override_band": r.get("override_band"),
            "observed_fields": r.get("observed_fields", {}),
            "facts": r.get("facts", []),
            "reason_text": r.get("reason_text", ""),
            "rationale": r.get("rationale", ""),
            "remediable": r.get("remediable", True),
            "ages_out_on": r.get("ages_out_on"),
            "kind": r.get("kind", "due_diligence"),
            "coverage_type": r.get("coverage_type", "full"),
            "source": {
                "raw_response_id": r.get("raw_response_id"),
                "observation_id": r.get("observation_id"),
            },
            "remediation": r.get("remediation", []),
        }
        for r in rule_results
    ]

    unassessed_signals = [
        {
            "signal_key": r["signal_key"],
            "signal_label": r.get("label") or r["signal_key"],
            "potential_points": r.get("potential_points", r.get("max_points", 0)),
            "provider": next(
                (f["value"] for f in r.get("facts", []) if f.get("label") == "Source"),
                "System default",
            ),
            "reason_not_assessed": r.get("reason_text", "No observation data collected yet"),
        }
        for r in rule_results
        if r.get("status") == "not_assessed"
    ]

    override_details = [
        {
            "rule_id": r["rule_id"],
            "signal_key": r["signal_key"],
            "override_band": r.get("override_band") or "High",
            "rationale": r.get("rationale") or r.get("reason_text", ""),
        }
        for r in rule_results
        if r.get("override_band")
    ]

    explanation = {
        "headline": headline,
        "final_band": final_band,
        "points_band": points_band,
        "rating_status": rating_status,
        "total_points": total_points,
        "weighted_points": weighted_points,
        "checked_max_points": checked_max_points,
        "missing_max_points": missing_max_points,
        "unverified_points": unverified_points,
        "unverified_signals": [r["signal_key"] for r in unverified],
        "gap_points": {r["signal_key"]: r["gap_points"] for r in unverified},
        "identity_verified": identity_verified,
        "data_needed": data_needed,
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
        "groups": groups_output,
        "arithmetic_line": arithmetic_line,
        "safety_notice": safety_notice,
        "attribution": "Breach data from Have I Been Pwned",
        "score_breakdown": score_breakdown,
        "signals": score_breakdown,
        "unassessed_signals": unassessed_signals,
        "override_details": override_details,
        "unassessed_potential_points": due_diligence_potential_points,
        "worst_case_points": worst_case_points,
        "worst_case_band": worst_case_band,
        "snapshot_sha256": snapshot_hash,
        "thought_process": thought_steps,
        "sum_check": {
            "sum_of_signal_points": total_points,
            "equals_total": True,
        },
        "change_since_last": change_since_last,
        "audit": {
            "assessed_at": assessed_at.isoformat(),
            # The governance version of the active ruleset (what GET /risk
            # reports), not the definition's schema version (G11).
            "ruleset_version": vendor_context.get("ruleset_version", ruleset.get("version", 2)),
            "definition_hash": definition_hash,
            "snapshot_sha256": snapshot_hash,
            "observation_ids": observation_ids,
            "trigger_type": trigger_type,
            "trigger_ref": trigger_ref,
        },
    }

    score_float = round(weighted_points / 100.0, 4)

    return {
        "total_points": total_points,
        "weighted_points": weighted_points,
        "checked_max_points": checked_max_points,
        "missing_max_points": missing_max_points,
        "unverified_points": unverified_points,
        "unverified_signals": [r["signal_key"] for r in unverified],
        "identity_verified": identity_verified,
        "data_needed": data_needed,
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
