"""What the user means, decided before anything is retrieved.

The assistant used to send every message straight to retrieval, so "hi" got
a canned line, "like what" was searched together with the previous message
and returned a random business rule, and "sure procurement is easy like
vendors" was answered as a lookup for a vendor called "sure procurement".
This module sorts a message first (plain rules, so each case is testable):

  greeting       hi, hello, good morning, thanks, bye      -> a natural reply
  capabilities   what can you do, help                      -> what it can do
  examples       like what, for example, such as            -> example questions
  smalltalk      a remark, not a question ("procurement is   -> acknowledge it and
                 easy like vendors", "ok cool")                offer the topic it names
  topic_only     just a topic: "vendors", "licences?"       -> a short clarifying question
  licence_anomalies  questions about licence usage anomalies -> live data (topics.py)
  question       anything else                              -> retrieval + generation

Replies to the conversational kinds are written here, not by the model:
they are short, never invent records and name real things the assistant can
look up. Examples are tailored to the user's role.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

STAFF = ("approver", "finance", "admin", "service")

TOPICS = {
    "vendors": r"vendors?|suppliers?",
    "contracts": r"contracts?|clauses?|agreements?|renewals?",
    "requests": r"(purchase )?requests?|orders?|approvals?",
    "licences": r"licen[cs]es?|seats?|saas|subscriptions?",
    "invoices": r"invoices?|bills?|payments?",
    "budgets": r"budgets?|spend(ing)?",
    "risk": r"risk|sanctions?|risk ratings?",
    "rules": r"rules?|policy|policies|thresholds?",
    "tax": r"gst|tds|tax(es)?|e-?invoices?",
}
_TOPIC_RE = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in TOPICS.items()}

_GREETING = re.compile(r"^\s*(hi+|hello+|hey+|hiya|yo|namaste|good\s+(morning|afternoon|evening|day)|greetings)"
                       r"(\s+(there|assistant|bot|team))?\s*[!.,]*\s*$", re.I)
_THANKS = re.compile(r"^\s*(thanks?( you)?( so much| a lot)?|thank you|ty|cheers|great,? thanks?|ok,? thanks?)\s*[!.]*\s*$", re.I)
_BYE = re.compile(r"^\s*(bye|goodbye|see you|see ya|that'?s all)\s*[!.]*\s*$", re.I)
_CAPABILITIES = re.compile(r"\b(what (can|do) you (do|help( me)? with|know)|how can you help|who are you|"
                           r"what are you|help me|^help\b|your capabilities)", re.I)
_EXAMPLES = re.compile(r"^\s*(like what|such as|for example|for instance|e\.?g\.?|examples?|any examples?|"
                       r"give( me)? (an |some )?examples?|show me (an |some )?examples?|what kind( of (things|questions))?|"
                       r"what sort of things|what questions( can i ask)?|what else)\s*[?!.]*\s*$", re.I)
_QUESTION_WORD = re.compile(r"^\s*(what|which|who|whom|whose|when|where|why|how|is|are|was|were|do|does|did|can|could|"
                            r"should|will|would|has|have|list|show|tell|give|find|get|explain|summari[sz]e|compare|"
                            r"any|how many|how much)\b", re.I)
_REMARK = re.compile(r"\b(sure|ok(ay)?|cool|nice|great|awesome|i see|i think|i guess|i feel|interesting|"
                     r"is (easy|hard|fun|boring|simple|complicated|interesting)|lol|haha|got it|makes sense|"
                     r"fair enough|alright|right)\b", re.I)
_LICENCE_ANOMALY = re.compile(r"(licen[cs]e|seat|saas|subscription|usage).*(anomal|unusual|under-?used|"
                              r"unused|idle|reclaim|decline|wast)|(anomal|unusual|under-?used|idle|reclaim).*"
                              r"(licen[cs]e|seat|saas|subscription|usage)", re.I)


@dataclass
class Intent:
    kind: str
    topic: Optional[str] = None
    topics: list = field(default_factory=list)


def topics_in(text: str) -> list[str]:
    return [k for k, rx in _TOPIC_RE.items() if rx.search(text or "")]


def classify(message: str, previous_user: Optional[str] = None) -> Intent:
    text = (message or "").strip()
    found = topics_in(text)
    if not text:
        return Intent("capabilities")
    if _GREETING.match(text) or _THANKS.match(text) or _BYE.match(text):
        return Intent("greeting")
    if _EXAMPLES.match(text):
        return Intent("examples", topics_in(previous_user or "")[0] if topics_in(previous_user or "") else None)
    if _CAPABILITIES.search(text):
        return Intent("capabilities")
    if _LICENCE_ANOMALY.search(text):
        return Intent("licence_anomalies", "licences", found)
    words = re.findall(r"[a-z0-9']+", text.lower())
    is_question = text.endswith("?") or bool(_QUESTION_WORD.match(text))
    if not is_question and found and len(words) <= 3 and all(any(_TOPIC_RE[t].fullmatch(w) for t in found) or
                                                           w in ("the", "my", "our", "about", "and") for w in words):
        return Intent("topic_only", found[0], found)
    if not is_question and (_REMARK.search(text) or len(words) <= 2):
        return Intent("smalltalk", found[0] if found else None, found)
    return Intent("question", found[0] if found else None, found)


# ── replies for the conversational kinds ────────────────────────────────────

EXAMPLES = {
    "vendors": ["What is the risk rating of {vendor}?", "Which vendors are rated High risk?"],
    "contracts": ["How much notice do we need to end a professional services contract?",
                  "What uptime does our SaaS subscription contract promise?"],
    "requests": ["What is the status of my most recent purchase request?",
                 "Who is my latest request waiting on?",
                 "How many purchase requests are waiting for approval?"],
    "licences": ["Are there any SaaS licence anomalies?", "Which licences have unassigned seats?"],
    "invoices": ["Who has to approve a purchase above 5,000 rupees?", "What happens if an invoice is above the PO price?"],
    "budgets": ["How much is left in the Engineering software budget this quarter?"],
    "risk": ["What is the risk rating of {vendor}?", "When does a vendor need a finance approval step?"],
    "rules": ["Who has to approve a purchase above 5,000 rupees?", "What is the licence anomaly threshold?"],
    "tax": ["What GST is checked on an invoice?"],
}
REQUESTER_TOPICS = ("requests", "vendors", "contracts", "rules")
# Examples about totals or other people's items, which a requester can't see.
STAFF_ONLY_EXAMPLES = {"How many purchase requests are waiting for approval?", "Which vendors are rated High risk?"}
STAFF_TOPICS = ("requests", "licences", "vendors", "contracts", "budgets")
LABEL = {"vendors": "vendors", "contracts": "contracts", "requests": "purchase requests", "licences": "software licences",
         "invoices": "invoices", "budgets": "budgets", "risk": "vendor risk", "rules": "the platform's rules",
         "tax": "GST and TDS"}


def _examples(topics: list[str], role: str, vendor: Optional[str], n: int = 3, shown: str = "") -> list[str]:
    """Up to n example questions for the topics (all topics the role may ask
    about when none is given), leaving out ones already shown and, for a
    requester, ones about data they can't see."""
    staff = role in STAFF
    allowed = [t for t in topics if staff or t not in ("licences", "budgets")]
    pool = allowed or list(STAFF_TOPICS if staff else REQUESTER_TOPICS)
    candidates = []
    for t in pool:
        candidates += [q.format(vendor=vendor or "a vendor") for q in EXAMPLES.get(t, [])
                       if staff or q not in STAFF_ONLY_EXAMPLES]
    fresh = [q for q in dict.fromkeys(candidates) if q not in (shown or "")]
    # Spread over topics: one per topic first, then the rest.
    first = [next((q for q in fresh if q in [x.format(vendor=vendor or "a vendor") for x in EXAMPLES.get(t, [])]), None)
             for t in pool]
    ordered = [q for q in first if q] + [q for q in fresh if q not in first]
    return (ordered or candidates)[:n]


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {q}" for q in items)


def reply(intent: Intent, message: str, *, role: str, first_name: Optional[str], vendor: Optional[str],
          shown: str = "") -> str:
    """The text for a conversational intent (never for kind 'question').
    `shown` is the assistant's previous message, so examples aren't repeated."""
    name = f" {first_name}" if first_name else ""
    if intent.kind == "greeting":
        text = message.strip().lower()
        if _THANKS.match(text):
            return "You're welcome! Ask me anything else about your purchases, vendors or contracts."
        if _BYE.match(text):
            return "Bye for now. I'm here whenever you need something on the platform."
        return (f"Hi{name}! I'm the procurement assistant. I answer from this platform's own records, for example:\n"
                f"{_bullets(_examples([], role, vendor))}\nWhat would you like to know?")
    if intent.kind == "capabilities":
        areas = ("your purchase requests, vendors and their risk, contract clauses and the platform's rules"
                 if role not in STAFF else
                 "purchase requests, approvals, vendors and their risk, contracts and their clauses, software "
                 "licences and their usage, budgets and the platform's rules")
        return (f"I can look up {areas}, and explain them in plain words with the record I used. "
                f"I can't change anything: approvals, signing and edits happen on each item's page. Try:\n"
                f"{_bullets(_examples([], role, vendor))}")
    if intent.kind == "examples":
        topics = [intent.topic] if intent.topic else []
        return f"Here are a few things you could ask:\n{_bullets(_examples(topics, role, vendor, 4, shown))}"
    if intent.kind == "topic_only":
        what = LABEL.get(intent.topic, intent.topic)
        return (f"What would you like to know about {what}? For example:\n"
                f"{_bullets(_examples([intent.topic], role, vendor))}")
    if intent.kind == "smalltalk":
        if intent.topic:
            what = LABEL.get(intent.topic, intent.topic)
            return (f"It can be! For {what} I can pull up the actual records here. You could ask:\n"
                    f"{_bullets(_examples([intent.topic], role, vendor))}")
        return ("Got it. If there's something on the platform you want to check, a request, a vendor, a contract "
                "or a rule, just ask.")
    raise ValueError(f"no canned reply for {intent.kind}")


# ── ambiguous names ─────────────────────────────────────────────────────────

_NAME_TOKEN = re.compile(r"\b([A-Z][A-Za-z0-9&.\-]{2,})\b")
_SKIP = {"What", "Which", "Who", "When", "Where", "Why", "How", "Is", "Are", "Does", "Do", "Can", "Show", "List",
         "Tell", "Give", "Find", "The", "Our", "My", "Vendor", "Vendors", "Supplier", "Contract", "Risk", "PO", "PR",
         "GST", "TDS", "SaaS", "INR", "High", "Low", "Medium", "Unrated", "Any", "Please", "I", "IT"}


def clarify_vendor(message: str, vendor_names: list[str]) -> Optional[str]:
    """A clarifying question when the message names a vendor ambiguously:
    a name word that starts several vendors' names and none in full."""
    text = message or ""
    lowered = text.lower()
    if any(v.lower() in lowered for v in vendor_names):
        return None
    for token in _NAME_TOKEN.findall(text):
        if token in _SKIP:
            continue
        hits = [v for v in vendor_names if re.search(rf"\b{re.escape(token)}\b", v, re.I)]
        if len(hits) > 1:
            shown = ", ".join(hits[:4]) + (f" and {len(hits) - 4} more" if len(hits) > 4 else "")
            return f"Which vendor do you mean: {shown}?"
    return None
