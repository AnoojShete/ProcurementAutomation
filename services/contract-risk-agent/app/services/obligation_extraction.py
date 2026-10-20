"""Contract obligations: what a signed contract commits the parties to after
signature (feature expansion Phase 2, docs/feature-expansion-plan.md).

Each obligation type has
  - regex rules that find the clause (a span) in the contract text,
  - a parser that turns the clause text into values (seats, %, months …),
  - for eight types, a CUAD category, so Legal-BERT (clause_model.py) can
    find the clause instead.

Which types use the model is decided by ml/evaluate_obligation_model.py on
CUAD's test split (docs/results/obligations.md), with the same rule as
FR-13: the model is used for a type only where its F1 beats the rules.
The decision is copied into MODEL_TYPES below. Everything found here is a
*proposal*: a person confirms each obligation before reminders start.
"""
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

# ── value parsers ────────────────────────────────────────────────────────────

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "twelve": 12, "eighteen": 18, "twenty-four": 24, "thirty": 30, "sixty": 60, "ninety": 90}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(_WORDS) + r")"


def _num(s: str) -> float:
    s = s.lower()
    return float(_WORDS[s]) if s in _WORDS else float(s)


def months_from(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(_NUM + r"\s*\(?\d*\)?[\s-]*(months?|years?)", text, re.I)
    if not m:
        return None
    n = _num(m.group(1))
    return int(n * 12 if m.group(2).lower().startswith("year") else n)


def days_from(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(_NUM + r"\s*\(?\d*\)?\s*(?:business\s+|calendar\s+)?days", text, re.I)
    return int(_num(m.group(1))) if m else None


def hours_from(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(_NUM + r"\s*hours", text, re.I)
    return int(_num(m.group(1))) if m else None


def pct_from(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:%|percent)", text, re.I)
    return float(m.group(1)) if m else None


def seats_from(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.search(r"(\d[\d,]*)\s*(?:named\s+|concurrent\s+|authori[sz]ed\s+)?(?:users|seats|licen[cs]es|devices|units)", text, re.I)
    return int(m.group(1).replace(",", "")) if m else None


def amount_from(text: Optional[str]) -> Optional[float]:
    """An amount in INR/Rs/₹ or USD/$, Indian digit grouping allowed."""
    if not text:
        return None
    m = re.search(r"(?:INR|Rs\.?|₹|USD|US\$|\$)\s*([\d,]+(?:\.\d+)?)", text, re.I)
    return float(m.group(1).replace(",", "")) if m else None


def _sla_value(text: str) -> dict:
    out = {}
    if m := re.search(r"(\d{2}(?:\.\d+)?)\s*%\s*(?:monthly\s+)?(?:uptime|availability)", text, re.I):
        out["uptime_pct"] = float(m.group(1))
    if m := re.search(r"credit\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%[^.]*?(?:each|every|per)\s+(\d+(?:\.\d+)?)\s*%", text, re.I | re.S):
        out["credit_pct_per_step"], out["step_pct"] = float(m.group(1)), float(m.group(2))
    if m := re.search(r"up to\s+(?:a maximum of\s+)?(\d+(?:\.\d+)?)\s*%", text, re.I):
        out["credit_cap_pct"] = float(m.group(1))
    return out


def _license_value(text: str) -> dict:
    out = {}
    if (n := seats_from(text)) is not None:
        out["seats"] = n
    if re.search(r"non-?transferable", text, re.I):
        out["non_transferable"] = True
    if m := re.search(r"(?:use|used)\s+(?:only\s+)?in\s+([A-Z][a-z]+)(?:\s+only)?", text):
        out["territory"] = m.group(1)
    return out


def _data_value(text: str) -> dict:
    out = {}
    if (h := hours_from(text)) is not None:
        out["breach_notice_hours"] = h
    if m := re.search(r"(?:return|delete)[^.]{0,80}?within\s+" + _NUM + r"\s*days", text, re.I):
        out["data_return_days"] = int(_num(m.group(1)))
    return out


def _liability_value(text: str) -> dict:
    out = {}
    if (mo := months_from(text)) is not None:
        out["fees_months"] = mo
    if (a := amount_from(text)) is not None:
        out["amount"] = a
    return out


@dataclass
class ObligationType:
    key: str
    label: str
    cuad_category: Optional[str]
    patterns: list
    parse: Callable[[str], dict]
    recurrence: str = "none"          # none | monthly | annual
    flags: int = re.I | re.S
    notes: str = ""
    examples: list = field(default_factory=list)


S = r"[^.;]"   # stay inside one sentence

TYPES: dict[str, ObligationType] = {t.key: t for t in [
    ObligationType(
        "sla_uptime", "SLA uptime and service credits", None,
        [r"\d{2}(?:\.\d+)?\s*%\s*(?:monthly\s+)?(?:uptime|availability)" + S + r"*",
         r"service credits?" + S + r"{0,200}"],
        _sla_value, recurrence="monthly", notes="Not a CUAD category: rules only."),
    ObligationType(
        "license_limit", "Licence limits (users, transfer, territory)", "License Grant",
        [r"(?:up to|maximum of|not more than|no more than)\s+\d[\d,]*\s*(?:named\s+|concurrent\s+)?(?:users|seats|licen[cs]es|devices)" + S + r"*",
         r"(?:grants?|granted)\s+(?:to\s+\w+\s+)?an?\s+(?:non-exclusive|limited|non-transferable)" + S + r"{0,200}licen[cs]e" + S + r"*",
         r"non-?transferable" + S + r"{0,120}licen[cs]e" + S + r"*"],
        _license_value),
    ObligationType(
        "price_cap", "Price increase cap", None,
        [r"(?:increase|price|fees?)" + S + r"{0,120}?(?:limited to|shall not exceed|not to exceed|capped at)\s*\d+(?:\.\d+)?\s*(?:%|percent)" + S + r"*"],
        lambda t: {"max_increase_pct": pct_from(t)} if pct_from(t) is not None else {},
        notes="CUAD's test split has no Price Restrictions examples, so it can't be evaluated: rules only."),
    ObligationType(
        "audit_rights", "Audit rights", "Audit Rights",
        [r"(?:right to|may|shall be entitled to)\s+(?:inspect\s+and\s+)?audit" + S + r"*",
         r"audit" + S + r"{0,80}(?:books|records|accounts|premises|use of)" + S + r"*"],
        lambda t: {k: v for k, v in {"days": days_from(t),
                                     "frequency": "annual" if re.search(r"once (?:per|a|in any) (?:year|calendar year|twelve)", t, re.I) else None}.items() if v},
        recurrence="annual"),
    ObligationType(
        "warranty", "Warranty duration", "Warranty Duration",
        [r"warrant(?:s|y|ies)?" + S + r"{0,150}?(?:period of|for a period of|for)\s+" + _NUM + r"\s*\(?\d*\)?\s*(?:months|years)" + S + r"*",
         r"warranty period" + S + r"*"],
        lambda t: {"months": months_from(t)} if months_from(t) else {}),
    ObligationType(
        "termination_convenience", "Termination for convenience", "Termination For Convenience",
        [r"terminat\w*" + S + r"{0,100}(?:for (?:its |any )?convenience|without cause|for any reason)" + S + r"*"],
        lambda t: {"days": days_from(t)} if days_from(t) else {}),
    ObligationType(
        "minimum_commitment", "Minimum commitment", "Minimum Commitment",
        [r"minimum\s+(?:of\s+)?\d[\d,]*\s*(?:named\s+)?(?:seats|users|licen[cs]es|units)" + S + r"*",
         r"minimum\s+(?:purchase|order|commitment|quantity|annual)" + S + r"*"],
        lambda t: {k: v for k, v in {"seats": seats_from(t), "months": months_from(t)}.items() if v}),
    ObligationType(
        "post_termination", "After termination (data return, transition)", "Post-Termination Services",
        [r"(?:after|following|upon)\s+(?:the\s+)?(?:termination|expiry|expiration)" + S + r"{0,160}(?:return|delete|transition|destroy)" + S + r"*",
         r"(?:return|delete|destroy)" + S + r"{0,80}data" + S + r"{0,80}(?:termination|expiry|expiration)" + S + r"*"],
        lambda t: {"days": days_from(t)} if days_from(t) else {}),
    ObligationType(
        "data_protection", "Data protection and breach notice", None,
        [r"(?:personal\s+)?data\s+breach" + S + r"{0,120}within\s+" + _NUM + r"\s*hours" + S + r"*",
         r"data protection" + S + r"*"],
        _data_value, notes="CUAD has no data-protection category: rules only."),
    ObligationType(
        "liability_cap", "Liability cap", "Cap On Liability",
        [r"(?:total|aggregate|maximum|entire)\s+liability" + S + r"{0,200}",
         r"liability" + S + r"{0,80}(?:shall not exceed|is capped at|limited to|not exceed)" + S + r"*"],
        _liability_value),
    ObligationType(
        "insurance", "Insurance", "Insurance",
        [r"maintain" + S + r"{0,80}insurance" + S + r"*",
         r"insurance" + S + r"{0,80}(?:coverage|policy|of at least|in the amount)" + S + r"*"],
        lambda t: {"amount": amount_from(t)} if amount_from(t) else {}),
]}

# Decided by ml/evaluate_obligation_model.py (docs/results/obligations.md):
# types whose clause the model finds better than the rules on CUAD's test
# split and also reads every template value (docs/results/obligations.md,
# 20 Oct 2026): licence limits F1 0.44 vs 0.41, termination for convenience
# 0.74 vs 0.25. Every other type uses the rules.
MODEL_TYPES: frozenset = frozenset({"license_limit", "termination_convenience"})


def rule_span(text: str, key: str) -> Optional[tuple[int, int]]:
    """First place the rules for this type match: (start, end) or None."""
    t = TYPES[key]
    for p in t.patterns:
        if m := re.search(p, text, t.flags):
            return m.span()
    return None


_SENTENCE_END = re.compile(r"\.(?!\d)|\n\s*\n")


def _sentence(text: str, start: int, end: int) -> str:
    """The clause text to show: the matched span widened to its sentence."""
    # A full stop ends a sentence unless a digit follows it ("99.9%").
    ends = [m.end() for m in _SENTENCE_END.finditer(text)]
    s = max([e for e in ends if e <= start], default=0)
    e = min([e for e in ends if e > end], default=len(text))
    clause = re.sub(r"\s+", " ", text[s:e]).strip()
    # Drop a section heading in capitals ("SERVICE LEVEL Provider shall …").
    return re.sub(r"^(?:\d+\.\s*)?(?:[A-Z]{2,}[ ,&-]*)+(?=[A-Z][a-z])", "", clause).strip()


def _clauses(text: str, key: str) -> list[tuple[int, int, str]]:
    """Every sentence a rule for this type matches (first match per rule),
    in text order: the SLA's uptime and its credit terms are usually in
    different sentences, and the value needs both."""
    t = TYPES[key]
    seen, out = set(), []
    for p in t.patterns:
        if m := re.search(p, text, t.flags):
            sentence = _sentence(text, *m.span())
            if sentence not in seen:
                seen.add(sentence)
                out.append((m.start(), m.end(), sentence))
    return sorted(out)


def extract_with_rules(text: str, keys=None) -> list[dict]:
    out = []
    for key in keys or TYPES:
        found = _clauses(text, key)
        if not found:
            continue
        clause = " ".join(c for _, _, c in found)
        out.append({"type": key, "clause_text": clause, "value": TYPES[key].parse(clause),
                    "extracted_by": "regex", "confidence": None, "span": [found[0][0], found[0][1]]})
    return out


def extract_with_model(text: str, keys, min_score: float = 0.0) -> list[dict]:
    """Legal-BERT passages for the given (CUAD-backed) types."""
    from app.services import clause_model
    out = []
    for key in keys:
        cat = TYPES[key].cuad_category
        if not cat:
            continue
        passage = clause_model.answer(text, clause_model.cuad_question(cat))
        if not passage or passage["score"] < min_score:
            continue
        clause = _sentence(text, passage["start"], passage["end"])
        out.append({"type": key, "clause_text": clause, "value": TYPES[key].parse(clause),
                    "extracted_by": "legal-bert-cuad", "confidence": passage["score"],
                    "span": [passage["start"], passage["end"]]})
    return out


def extract_obligations(text: str, use_model: bool, min_score: float = 0.0) -> list[dict]:
    """Model for the adopted types (when available), rules for the rest and
    as the fallback when the model finds nothing for an adopted type."""
    model_keys = [k for k in TYPES if k in MODEL_TYPES] if use_model else []
    found = {o["type"]: o for o in extract_with_model(text, model_keys, min_score)} if model_keys else {}
    rest = [k for k in TYPES if k not in found]
    found.update({o["type"]: o for o in extract_with_rules(text, rest)})
    return [found[k] for k in TYPES if k in found]


def sla_credit(value: dict, measured_uptime_pct: float, monthly_fee: float) -> dict:
    """Service credit for one month: credit_pct_per_step for every step_pct
    (or part of it) the measured uptime falls below the committed uptime,
    capped at credit_cap_pct. {"credit_pct", "credit_amount", "shortfall_pct"}."""
    committed = value.get("uptime_pct")
    per_step, step = value.get("credit_pct_per_step"), value.get("step_pct")
    if committed is None or per_step is None or not step:
        return {"credit_pct": 0.0, "credit_amount": 0.0, "shortfall_pct": None, "reason": "no credit terms"}
    shortfall = round(max(committed - measured_uptime_pct, 0.0), 4)
    if shortfall <= 0:
        return {"credit_pct": 0.0, "credit_amount": 0.0, "shortfall_pct": 0.0}
    steps = math.ceil(round(shortfall / step, 6))
    pct = steps * per_step
    if value.get("credit_cap_pct") is not None:
        pct = min(pct, value["credit_cap_pct"])
    return {"credit_pct": pct, "credit_amount": round(monthly_fee * pct / 100, 2), "shortfall_pct": shortfall}
