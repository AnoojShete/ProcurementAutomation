"""The assistant's retrieval-augmented pipeline: what gets indexed (and
masked), how contracts are chunked, who may retrieve what, how hits are
ranked, and what the model is given. The live behaviour is checked by
tests/e2e/chatbot_eval.py."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import indexer, llm_client, rag_service
from shared.auth.middleware import CurrentUser


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── indexing ─────────────────────────────────────────────────────────────────

def test_bank_details_never_reach_the_index():
    raw = ("Bank Account Number: 50100123456789\nRouting/IFSC Code: HDFC0001234\n"
           "Pay to account 123456789012 by 30 Oct. Invoice INV-2026-00004.")
    masked = indexer.mask_sensitive(raw)
    assert "50100123456789" not in masked and "HDFC0001234" not in masked and "123456789012" not in masked
    assert "INV-2026-00004" in masked


CONTRACT = """PROFESSIONAL SERVICES AGREEMENT
Contract ID: abc

7. LIABILITY AND INSURANCE
   Consultant's total liability under this agreement shall not exceed the
   fees paid in the 12 months preceding the claim. Consultant shall maintain
   professional indemnity insurance of at least INR 50,00,000.

8. SIGNATURES
   Client: ______
"""


def test_contract_split_by_clause_and_sentence():
    parts = indexer.split_contract(CONTRACT)
    heads = [h for h, _ in parts]
    assert heads[0] == "Parties and dates" and "7. Liability And Insurance" in heads and "8. Signatures" in heads
    liability = [t for h, t in parts if h == "7. Liability And Insurance"]
    # One obligation per chunk: the cap and the insurance amount are apart.
    assert any("12 months" in t and "50,00,000" not in t for t in liability)
    assert any("50,00,000" in t and "12 months" not in t for t in liability)


def test_long_text_is_windowed_with_overlap():
    text = ". ".join(f"Sentence number {i} about the invoice" for i in range(120))
    windows = indexer._windows(text)
    assert len(windows) > 1 and all(len(w) <= indexer.WINDOW + 5 for w in windows)
    assert windows[0][-60:].split()[-1] in windows[1]          # overlap carries context across


def test_spend_tiers_are_written_in_words():
    tiers = [{"tier_name": "auto", "min_amount": 0, "max_amount": 500, "required_roles": []},
             {"tier_name": "manager", "min_amount": 500, "max_amount": 5000, "required_roles": ["dept_manager"]},
             {"tier_name": "manager+finance", "min_amount": 5000, "max_amount": None,
              "required_roles": ["dept_manager", "finance_head"]}]
    text = indexer.rule_value_text("approval.spend_tiers", tiers)
    assert "up to INR 500 are approved automatically" in text
    assert "above INR 5,000 are approved by the department manager, then the finance head" in text
    assert indexer.rule_value_text("x", True) == "on"


def test_sync_reembeds_only_what_changed():
    chunk = indexer.Chunk("rule", "a.b", "rule a.b", None, 0, "text", "all", None, "h-new")
    same = indexer.Chunk("rule", "c.d", "rule c.d", None, 0, "text", "all", None, "h-same")
    db = MagicMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    factory = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=False)))
    embed = AsyncMock(return_value=[[0.1] * 768])
    with patch.object(indexer, "load_sources", AsyncMock(return_value={("rule", "a.b"): [chunk], ("rule", "c.d"): [same]})), \
            patch.object(indexer, "stored_hashes", AsyncMock(return_value={("rule", "a.b"): "h-old", ("rule", "c.d"): "h-same",
                                                                         ("rule", "gone"): "h"})), \
            patch.object(indexer, "embed", embed):
        result = run(indexer.sync(factory))
    assert result == {"sources": 2, "changed": 1, "removed": 1, "chunks_embedded": 1}
    embed.assert_awaited_once()


# ── retrieval ────────────────────────────────────────────────────────────────

def _row(source_type, doc, title, distance, section=None):
    return SimpleNamespace(source_type=source_type, document_id=doc, title=title, section=section,
                           chunk_text=f"{title} text", distance=distance)


def _retrieve(user, rows):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=rows)))
    with patch.object(rag_service.indexer, "embed", AsyncMock(return_value=[[0.0] * 768])):
        hits = run(rag_service.retrieve(db, user, "liability cap in professional services contracts"))
    return hits, db.execute.await_args.args[1]


@pytest.mark.parametrize("role,staff", [("requester", False), ("approver", True), ("finance", True), ("admin", True)])
def test_access_is_applied_in_the_query(role, staff):
    _, params = _retrieve(CurrentUser(id="u", email="Alice@Acme.test", role=role), [])
    assert params["staff"] is staff and params["email"] == "alice@acme.test"


def test_access_clause_limits_owner_chunks_to_their_owner():
    import inspect
    src = inspect.getsource(rag_service.retrieve)
    assert "(e.audience = 'all' OR :staff OR (e.audience = 'owner' AND e.owner_email = :email))" in src


def test_named_contract_type_wins_and_far_hits_are_dropped():
    rows = [_row("contract", "c1", "CT-c1 · SaaS subscription · Acme", 0.20, "10. Liability"),
            _row("contract", "c2", "CT-c2 · Professional services · Beta", 0.25, "7. Liability"),
            _row("rule", "r1", "rule risk.x", 0.70)]
    hits, _ = _retrieve(CurrentUser(id="u", email="f@x", role="finance"), rows)
    assert [h.ref for h in hits] == ["CT-c2"]


def test_one_kind_of_source_cannot_crowd_out_the_rest():
    rows = [_row("request", f"r{i}", f"PR-r{i} · purchase request", 0.20 + i / 100) for i in range(rag_service.MAX_PER_TYPE["request"] + 2)]
    rows.append(_row("rule", "approval.spend_tiers", "rule approval.spend_tiers", 0.30))
    hits, _ = _retrieve(CurrentUser(id="u", email="f@x", role="finance"), rows)
    assert sum(h.source_type == "request" for h in hits) == rag_service.MAX_PER_TYPE["request"]
    assert any(h.ref == "approval.spend_tiers" for h in hits)


# ── generation ───────────────────────────────────────────────────────────────

def _msg(role, content):
    return SimpleNamespace(role=role, content=content)


def test_model_gets_the_passages_with_the_question_and_no_tools():
    hits = [rag_service.Hit("CT-3c90af41", "contract", "c", "t", "7. Liability", "fees paid in the 12 months", 0.2)]
    msgs = llm_client.build_messages([_msg("user", "What is the liability cap?")], CurrentUser(id="u", email="f@x", role="finance"), hits)
    assert msgs[0]["role"] == "system" and "Use only the PASSAGES" in msgs[0]["content"]
    assert '<document id="CT-3c90af41">\nfees paid in the 12 months' in msgs[-1]["content"] and "QUESTION: What is the liability cap?" in msgs[-1]["content"]

    post = AsyncMock(return_value=MagicMock(raise_for_status=MagicMock(), json=MagicMock(return_value={"message": {"content": "ok"}})))
    client = MagicMock(post=post)
    with patch.object(llm_client.rag_service, "retrieve", AsyncMock(return_value=hits)), \
            patch.object(llm_client.httpx, "AsyncClient", return_value=MagicMock(__aenter__=AsyncMock(return_value=client),
                                                                               __aexit__=AsyncMock(return_value=False))):
        assert run(llm_client.query_llm_with_tools([_msg("user", "What is the liability cap?")], CurrentUser(id="u", email="f@x", role="finance"), MagicMock())) == "ok"
    assert "tools" not in post.await_args.kwargs["json"]


def test_no_passages_tells_the_model_so():
    assert "No matching passages" in rag_service.as_context([])


def test_short_follow_up_is_searched_with_the_previous_question():
    history = [_msg("user", "How long is the warranty in our hardware contracts?"), _msg("assistant", "36 months."),
               _msg("user", "and for repairs?")]
    assert llm_client.search_query(history) == "How long is the warranty in our hardware contracts? and for repairs?"
    assert llm_client.search_query(history[:1]) == "How long is the warranty in our hardware contracts?"
