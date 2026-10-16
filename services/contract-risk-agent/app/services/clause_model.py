"""Clause extraction with Legal-BERT fine-tuned on CUAD (FR-13).

`alex-apostolo/legal-bert-base-cuad` is a question-answering model: given a
contract and one of CUAD's questions ("…related to "Renewal Term"…") it
returns the passage that answers it, or nothing. We ask three questions —
renewal term, notice period to terminate renewal, expiration date — and
turn each passage into a value with the small parsers in
clause_extraction.py (auto/manual, days, a date).

The model is loaded from the local Hugging Face cache only
(`./scripts/download-models.sh`), like LayoutLMv3; until it has been
downloaded, `available()` is False and the router uses the rules.
Evaluation against the rules on CUAD's test contracts:
docs/results/clauses.md (ml/evaluate_clause_model.py).
"""
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_ID = "alex-apostolo/legal-bert-base-cuad"

# CUAD's own question wording — the model was trained on exactly these.
_Q = 'Highlight the parts (if any) of this contract related to "{}" that should be reviewed by a lawyer. Details: {}'
QUESTIONS = {
    "renewal_type": _Q.format(
        "Renewal Term",
        "What is the renewal term after the initial term expires? This includes automatic extensions and "
        "unilateral extensions with prior notice."),
    "notice_period_days": _Q.format(
        "Notice Period To Terminate Renewal", "What is the notice period required to terminate renewal?"),
    "contract_end_date": _Q.format("Expiration Date", "On what date will the contract's initial term expire?"),
}
CUAD_CATEGORY = {"renewal_type": "Renewal Term", "notice_period_days": "Notice Period To Terminate Renewal",
                 "contract_end_date": "Expiration Date"}

MAX_LEN, STRIDE, MAX_ANSWER_TOKENS, TOP_N, BATCH = 384, 128, 120, 20, 16

_lock = threading.Lock()
_state: dict = {}


def _load():
    """(tokenizer, model), loaded once; None if the model isn't cached or
    torch/transformers aren't installed."""
    with _lock:
        if "model" in _state:
            return _state["model"]
        try:
            from transformers import AutoModelForQuestionAnswering, AutoTokenizer
            tok = AutoTokenizer.from_pretrained(MODEL_ID, local_files_only=True)
            model = AutoModelForQuestionAnswering.from_pretrained(MODEL_ID, local_files_only=True).eval()
            _state["model"] = (tok, model)
            logger.info(f"Clause model {MODEL_ID} loaded")
        except Exception as e:
            logger.warning(f"Clause model {MODEL_ID} unavailable, clauses use the rules: {e}")
            _state["model"] = None
        return _state["model"]


def available() -> bool:
    return _load() is not None


def answer(text: str, question: str) -> Optional[dict]:
    """Best passage for one question: {"text", "start", "end", "score"},
    or None when the model's best answer is "not in this contract".

    Standard extractive QA (SQuAD 2.0 style): the contract is cut into
    overlapping 384-token windows; in each, the best start/end pair inside
    the contract text is scored start_logit + end_logit. The answer is the
    best span over all windows if it beats the "no answer" score (the
    [CLS] position), and `score` is that margin."""
    loaded = _load()
    if loaded is None:
        raise RuntimeError("clause model not available")
    import torch
    tok, model = loaded
    enc = tok(question, text, truncation="only_second", max_length=MAX_LEN, stride=STRIDE,
              return_overflowing_tokens=True, return_offsets_mapping=True, padding="max_length", return_tensors="pt")
    offsets = enc.pop("offset_mapping")
    enc.pop("overflow_to_sample_mapping", None)
    best, null = None, None
    for b in range(0, enc["input_ids"].shape[0], BATCH):
        batch = {k: v[b:b + BATCH] for k, v in enc.items()}
        with torch.no_grad():
            out = model(**batch)
        for i in range(out.start_logits.shape[0]):
            w = b + i
            starts, ends = out.start_logits[i], out.end_logits[i]
            cls = float(starts[0] + ends[0])
            null = cls if null is None else min(null, cls)
            in_context = [j for j, s in enumerate(enc.sequence_ids(w)) if s == 1]
            lo, hi = in_context[0], in_context[-1]
            top_s = [j for j in torch.argsort(starts, descending=True)[:TOP_N].tolist() if lo <= j <= hi]
            top_e = [j for j in torch.argsort(ends, descending=True)[:TOP_N].tolist() if lo <= j <= hi]
            for s in top_s:
                for e in top_e:
                    if s <= e < s + MAX_ANSWER_TOKENS:
                        score = float(starts[s] + ends[e])
                        if best is None or score > best[0]:
                            best = (score, int(offsets[w][s][0]), int(offsets[w][e][1]))
    if best is None or best[0] <= null:
        return None
    score, start, end = best
    return {"text": text[start:end], "start": start, "end": end, "score": round(score - null, 3)}


def find_passages(text: str) -> dict:
    """{field: passage or None} for the three clauses."""
    return {field: answer(text, q) for field, q in QUESTIONS.items()}
