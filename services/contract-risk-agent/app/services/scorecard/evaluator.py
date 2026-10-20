"""Safe evaluator for deterministic scorecard rules (Prompt 9B section 3).
Evaluates `when` clauses with NO eval, NO code strings, NO Jinja logic.
A comparison against a null/missing field is always false (never an error),
except `is_null` which evaluates to true.
"""
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union


def format_date_human(val: Any) -> str:
    """Renders date as DD Mon YYYY."""
    if not val:
        return "—"
    dt = None
    if isinstance(val, (datetime, date)):
        dt = val
    elif isinstance(val, str):
        val_clean = val.strip()
        # Try ISO formats
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(val_clean.replace("Z", "+0000"), fmt)
                break
            except ValueError:
                continue
    if dt:
        return dt.strftime("%d %b %Y")
    return str(val)


def format_value(val: Any) -> str:
    """Formats values for template display according to field catalogue rules."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, (datetime, date)):
        return format_date_human(val)
    if isinstance(val, float):
        # Format integer-equivalent floats or round to 2dp
        if val.is_integer():
            return str(int(val))
        return f"{val:.2f}"
    return str(val)


class SafeEvaluator:
    """Evaluates rule conditions against a flat map of observed fields."""

    SUPPORTED_OPS = {"eq", "ne", "in", "not_in", "lt", "lte", "gt", "gte", "between", "is_null", "not_null"}

    @classmethod
    def evaluate(cls, condition: Optional[Dict[str, Any]], fields: Dict[str, Any]) -> bool:
        """Evaluates a condition dict against fields. If condition is None or empty, returns True (else rule)."""
        if condition is None or not condition:
            return True

        if "all" in condition:
            return all(cls.evaluate(c, fields) for c in condition["all"])
        if "any" in condition:
            return any(cls.evaluate(c, fields) for c in condition["any"])
        if "not" in condition:
            sub = condition["not"]
            return not cls.evaluate(sub, fields)

        # Single clause: {"field": "...", "op": "...", "value": ...}
        field_name = condition.get("field")
        op = condition.get("op")
        expected = condition.get("value")

        if not field_name or not op:
            return False

        if op not in cls.SUPPORTED_OPS:
            return False

        field_val = fields.get(field_name)

        # Special operators for null
        if op == "is_null":
            return field_val is None or field_val == ""
        if op == "not_null":
            return field_val is not None and field_val != ""

        # Any other operator against null is FALSE (never an error)
        if field_val is None:
            return False

        # Numeric and string type coercions where appropriate
        try:
            if op == "eq":
                if isinstance(field_val, (int, float)) and isinstance(expected, (int, float)):
                    return float(field_val) == float(expected)
                return str(field_val).lower() == str(expected).lower() if isinstance(field_val, str) and isinstance(expected, str) else field_val == expected

            if op == "ne":
                if isinstance(field_val, (int, float)) and isinstance(expected, (int, float)):
                    return float(field_val) != float(expected)
                return str(field_val).lower() != str(expected).lower() if isinstance(field_val, str) and isinstance(expected, str) else field_val != expected

            if op == "in":
                if not isinstance(expected, (list, tuple, set)):
                    return False
                if isinstance(field_val, str):
                    return any(str(field_val).lower() == str(e).lower() for e in expected)
                return field_val in expected

            if op == "not_in":
                if not isinstance(expected, (list, tuple, set)):
                    return False
                if isinstance(field_val, str):
                    return not any(str(field_val).lower() == str(e).lower() for e in expected)
                return field_val not in expected

            if op in ("lt", "lte", "gt", "gte"):
                f_num = float(field_val)
                e_num = float(expected)
                if op == "lt":
                    return f_num < e_num
                if op == "lte":
                    return f_num <= e_num
                if op == "gt":
                    return f_num > e_num
                if op == "gte":
                    return f_num >= e_num

            if op == "between":
                if not isinstance(expected, (list, tuple)) or len(expected) != 2:
                    return False
                f_num = float(field_val)
                low = float(expected[0])
                high = float(expected[1])
                return low <= f_num <= high

        except (ValueError, TypeError):
            return False

        return False


def render_template(template: str, context: Dict[str, Any]) -> str:
    """Replaces {field.name} and system placeholders safely.
    Missing variables resolve to empty string or default without raising KeyError.
    """
    if not template:
        return ""

    def replace_match(match):
        key = match.group(1).strip()
        val = context.get(key)
        if val is None:
            # Check if key is a date or ends with _date / _at
            if "date" in key or "at" in key or "on" in key:
                return "—"
            return "—"
        if isinstance(val, (datetime, date)):
            return format_date_human(val)
        if isinstance(val, float):
            if val.is_integer():
                return str(int(val))
            return f"{val:.2f}" if "composite" in key or "rate" in key or "score" in key else f"{val:.1f}"
        return str(val)

    # Replace all {var.name} or {var}
    return re.sub(r"\{([a-zA-Z0-9_\.]+)\}", replace_match, template)
