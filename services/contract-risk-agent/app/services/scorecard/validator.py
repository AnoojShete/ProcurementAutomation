"""Ruleset validation according to Prompt 9B section 3.4.
Enforces the 8 publish-time validation checks and returns field-level error details.
"""
import re
from typing import Any, Dict, List, Tuple
from app.services.scorecard.field_catalogue import SIGNAL_FIELD_CATALOGUE, GLOBAL_PLACEHOLDERS


class RulesetValidationError(ValueError):
    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        message = "; ".join(f"{e.get('field', 'ruleset')}: {e.get('message')}" for e in errors)
        super().__init__(message)


VALID_OPERATORS = {
    "eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "is_null", "not_null"
}


def extract_template_placeholders(template: str) -> List[str]:
    """Extracts all variable placeholders inside `{...}`."""
    if not template:
        return []
    return re.findall(r"\{([a-zA-Z0-9_\.]+)\}", template)


def validate_when_condition(when: Any, path: str, errors: List[Dict[str, str]]) -> None:
    """Recursively validates a 'when' condition tree according to Section 3.2."""
    if not isinstance(when, dict):
        errors.append({"field": path, "message": "when condition must be an object"})
        return
    for k, v in when.items():
        if k in ("all", "any"):
            if not isinstance(v, list):
                errors.append({"field": f"{path}.{k}", "message": f"{k} must be a list of conditions"})
            else:
                for idx, item in enumerate(v):
                    validate_when_condition(item, f"{path}.{k}[{idx}]", errors)
        elif k == "not":
            validate_when_condition(v, f"{path}.not", errors)
        elif k == "op":
            if v not in VALID_OPERATORS:
                errors.append({"field": f"{path}.op", "message": f"unknown operator '{v}'"})
        elif k in ("field", "value"):
            pass
        else:
            errors.append({"field": f"{path}.{k}", "message": f"unknown property '{k}' in condition"})


def validate_ruleset(ruleset: Dict[str, Any]) -> Tuple[bool, List[Dict[str, str]]]:
    """Validates ruleset definition against Section 3.4 criteria.
    Returns (is_valid, errors_list).
    """
    errors: List[Dict[str, str]] = []

    # Check top-level bands: 0 <= low_max < medium_max < 100 (Check e)
    bands = ruleset.get("bands")
    if not isinstance(bands, dict):
        errors.append({"field": "bands", "message": "bands must be an object with low_max and medium_max"})
    else:
        low_max = bands.get("low_max")
        medium_max = bands.get("medium_max")
        if not isinstance(low_max, int) or not isinstance(medium_max, int):
            errors.append({"field": "bands", "message": "low_max and medium_max must be integers"})
        elif not (0 <= low_max < medium_max < 100):
            errors.append({"field": "bands", "message": f"bands must satisfy 0 <= low_max ({low_max}) < medium_max ({medium_max}) < 100"})

    signals = ruleset.get("signals")
    if not isinstance(signals, list) or len(signals) == 0:
        errors.append({"field": "signals", "message": "signals must be a non-empty list"})
        return len(errors) == 0, errors

    # Check a: sum of max_points over all signals == 100
    sum_max_points = 0
    all_rule_ids = set()

    for s_idx, signal in enumerate(signals):
        s_key = signal.get("key", f"signals[{s_idx}]")
        max_points = signal.get("max_points")
        if not isinstance(max_points, int) or max_points < 0:
            errors.append({"field": f"signals[{s_key}].max_points", "message": "max_points must be an integer >= 0"})
        else:
            sum_max_points += max_points

        outcomes = signal.get("outcomes")
        if not isinstance(outcomes, list) or len(outcomes) == 0:
            errors.append({"field": f"signals[{s_key}].outcomes", "message": "outcomes must be a non-empty list"})
            continue

        highest_outcome_points = -1
        has_remediation_target = False
        all_remediable_false = True

        for o_idx, outcome in enumerate(outcomes):
            rule_id = outcome.get("rule_id", f"{s_key}_outcome_{o_idx}")
            points = outcome.get("points")
            status = outcome.get("status")
            when = outcome.get("when")
            override_band = outcome.get("override_band")
            remediation_target = outcome.get("remediation_target", False)
            remediable = outcome.get("remediable", True)

            # Check d: rule_id unique, points are integers >= 0
            if rule_id in all_rule_ids:
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].rule_id", "message": f"Duplicate rule_id '{rule_id}'"})
            else:
                all_rule_ids.add(rule_id)

            if not isinstance(points, int) or points < 0:
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].points", "message": f"Rule {rule_id} points must be integer >= 0"})
            else:
                if points > highest_outcome_points:
                    highest_outcome_points = points

            # Check h: override_band, if present, is "High" or "Medium"
            if override_band is not None and override_band not in ("High", "Medium"):
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].override_band", "message": f"Rule {rule_id} override_band must be 'High' or 'Medium', got '{override_band}'"})

            # Prompt 9C: short_circuit_external allowed only on outcomes that also have override_band
            short_circuit = outcome.get("short_circuit_external", False)
            if short_circuit and not override_band:
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].short_circuit_external", "message": f"Rule {rule_id} short_circuit_external=true is only allowed on outcomes with override_band"})

            # Prompt 9C: assessed_no_finding status allowed only on detect_only signals
            cov_type = signal.get("coverage_type", "full")
            if status == "assessed_no_finding" and cov_type != "detect_only":
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].status", "message": f"Rule {rule_id} status 'assessed_no_finding' is allowed only on detect_only signals, got coverage_type '{cov_type}'"})

            # Prompt 9C: detect_only signals never add potential points
            potential_pts = outcome.get("potential_points", 0)
            if cov_type == "detect_only" and potential_pts > 0:
                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].potential_points", "message": f"Rule {rule_id} belongs to detect_only signal '{s_key}' and must not specify potential_points > 0, got {potential_pts}"})

            if when is not None and when != {}:
                validate_when_condition(when, f"signals[{s_key}].outcomes[{o_idx}].when", errors)

            # Track remediation target
            if remediation_target is True:
                has_remediation_target = True
            if remediable is True:
                all_remediable_false = False

            # Check f: placeholder resolution against catalogue
            allowed_for_signal = SIGNAL_FIELD_CATALOGUE.get(s_key, set()) | GLOBAL_PLACEHOLDERS
            reason_template = outcome.get("reason", "")
            for p in extract_template_placeholders(reason_template):
                if p not in allowed_for_signal and not p.startswith(s_key) and p not in GLOBAL_PLACEHOLDERS:
                    errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].reason", "message": f"Unknown placeholder '{{{p}}}' in rule {rule_id}"})

            remediation = outcome.get("remediation")
            if isinstance(remediation, list):
                for r_item in remediation:
                    if isinstance(r_item, dict):
                        for p in extract_template_placeholders(r_item.get("step", "")):
                            if p not in allowed_for_signal and not p.startswith(s_key) and p not in GLOBAL_PLACEHOLDERS:
                                errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].remediation", "message": f"Unknown placeholder '{{{p}}}' in rule {rule_id} step"})

            # Check c: last outcome has no `when` (the else) and status not_assessed or not_applicable
            is_last = (o_idx == len(outcomes) - 1)
            if is_last:
                if when is not None and when != {}:
                    errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].when", "message": f"The last outcome (rule {rule_id}) must have no 'when' condition (else fallback)"})
                if status not in ("not_assessed", "not_applicable"):
                    errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].status", "message": f"The last outcome (rule {rule_id}) status must be 'not_assessed' or 'not_applicable', got '{status}'"})
            else:
                if when is None or when == {}:
                    errors.append({"field": f"signals[{s_key}].outcomes[{o_idx}].when", "message": f"Intermediate outcome (rule {rule_id}) must specify a 'when' condition"})

        # Check b: for each signal, max_points == highest points among its outcomes
        if highest_outcome_points != max_points:
            errors.append({"field": f"signals[{s_key}].max_points", "message": f"Signal '{s_key}' max_points ({max_points}) does not match highest outcome points ({highest_outcome_points})"})

        # Check g: each signal has exactly one outcome with remediation_target=true or explicitly none with remediable=false on all outcomes
        if not has_remediation_target and not all_remediable_false:
            errors.append({"field": f"signals[{s_key}]", "message": f"Signal '{s_key}' must have exactly one outcome with remediation_target=true or all outcomes with remediable=false"})

    # Check a completion: sum of max_points == 100
    if sum_max_points != 100:
        errors.append({"field": "signals", "message": f"Sum of max_points across all signals must equal 100, got {sum_max_points}"})

    # Prompt 9C: detect_only signals may not appear in any required-signals list
    detect_only_keys = {s.get("key") for s in signals if s.get("coverage_type") == "detect_only"}
    required_map = ruleset.get("required_signals_by_tier") or ruleset.get("required_signals") or {}
    if isinstance(required_map, dict):
        for tier, req_sigs in required_map.items():
            if isinstance(req_sigs, (list, tuple, set)):
                for sig in req_sigs:
                    if sig in detect_only_keys:
                        errors.append({
                            "field": f"required_signals.{tier}",
                            "message": f"detect_only signal '{sig}' may not appear in any required-signals list",
                        })

    return len(errors) == 0, errors
