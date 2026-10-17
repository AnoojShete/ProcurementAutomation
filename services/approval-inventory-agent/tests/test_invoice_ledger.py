"""app/services/invoice_ledger.py — the pure matching rules."""
from app.services.invoice_ledger import Candidate, InvoiceLine, POLine, Tolerances, evaluate, po_lines_from_items

TOL = Tolerances()
LAPTOPS = [POLine(0, "Dell Latitude 5440 Laptop", 10, 78500.0), POLine(1, "USB-C Dock", 10, 8900.0)]


def cand(req_id="po-1", status="fulfilled", amount=1_031_320.0, invoiced=0.0, qty=None, lines=LAPTOPS):
    return Candidate(req_id, status, amount, lines, invoiced, qty or {})


def test_items_json_to_lines():
    lines = po_lines_from_items([
        {"name": "Seat", "quantity": 2, "unit_price": 1650},
        {"description": "Bad", "quantity": 0, "unit_price": 1},
    ])
    assert [(l.description, l.quantity) for l in lines] == [("Seat", 2)]


def test_full_invoice_against_fulfilled_request_matches():
    # The old match only looked at `approved` requests, so this invoice —
    # arriving after the contract was signed — could never match.
    r = evaluate(1_031_320.0, [InvoiceLine("Dell Latitude 5440 Laptop", 10, 78500), InvoiceLine("USB-C Dock", 10, 8900)],
                 [cand()], TOL)
    assert r.status == "matched" and r.request_id == "po-1"
    assert r.remaining_after == 0
    assert {a["line_no"] for a in r.allocations} == {0, 1}


def test_partial_invoice_leaves_balance():
    r = evaluate(370_550.0, [InvoiceLine("Latitude 5440", 4, 78500)], [cand()], TOL)
    assert r.status == "partial"
    assert r.remaining_after == round(1_031_320.0 - 370_550.0, 2)


def test_overbilled_unit_price_is_a_variance_not_a_match():
    # Old rule: header total within ±5% passed. 2% over on price now doesn't.
    r = evaluate(1_051_946.4, [InvoiceLine("Dell Latitude 5440 Laptop", 10, 80070), InvoiceLine("USB-C Dock", 10, 8900)],
                 [cand()], TOL)
    assert r.status == "variance"
    assert any("above the agreed" in i for i in r.issues)
    assert r.allocations == []


def test_more_quantity_than_left_is_a_variance():
    already = cand(invoiced=740_950.0, qty={0: 8})
    r = evaluate(185_260.0, [InvoiceLine("Dell Latitude 5440 Laptop", 2, 78500)], [already], TOL)
    assert r.status == "partial"  # exactly the 2 laptops left; the docks are still open
    r = evaluate(277_890.0, [InvoiceLine("Dell Latitude 5440 Laptop", 3, 78500)], [already], TOL)
    assert r.status == "variance" and any("only 2 left" in i for i in r.issues)


def test_second_invoice_for_fully_invoiced_request_is_caught():
    done = cand(status="partially_invoiced", invoiced=1_031_320.0, qty={0: 10, 1: 10})
    r = evaluate(1_031_320.0, [InvoiceLine("Dell Latitude 5440 Laptop", 10, 78500)], [done], TOL)
    assert r.status == "variance"
    assert any("fully invoiced" in i or "only 0 left" in i for i in r.issues)


def test_underbilling_is_fine():
    r = evaluate(1_000_000.0, [InvoiceLine("Dell Latitude 5440 Laptop", 10, 76000), InvoiceLine("USB-C Dock", 10, 8900)],
                 [cand()], TOL)
    assert r.status in ("matched", "partial")


def test_header_only_invoice_matches_on_balance():
    r = evaluate(3894.0, [], [cand(amount=3894.0, lines=[])], TOL)
    assert r.status == "matched"
    assert r.allocations[0]["amount"] == 3894.0


def test_two_equal_candidates_is_ambiguous_unless_one_is_exact():
    a, b = cand("po-a", amount=5000.0, lines=[]), cand("po-b", amount=5000.0, lines=[])
    assert evaluate(5000.0, [], [a, b], TOL).status == "ambiguous"
    c = cand("po-c", amount=9000.0, lines=[])
    r = evaluate(5000.0, [], [a, c], TOL)
    assert r.status == "matched" and r.request_id == "po-a"


def test_unrelated_invoice_is_no_match():
    r = evaluate(12.0, [InvoiceLine("Office chairs", 3, 4)], [cand()], TOL)
    assert r.status == "no_match"


def test_po_reference_on_the_invoice_resolves_identical_requests():
    a = cand("9e085e38-e1a5-47e9-b8b4-588b3299e772", amount=5000.0, lines=[])
    b = cand("049f69bd-420a-49b3-b115-4d0ffbe78a1f", amount=5000.0, lines=[])
    assert evaluate(5000.0, [], [a, b], TOL).status == "ambiguous"
    r = evaluate(5000.0, [], [a, b], TOL, po_ref="PO-049F69BD")
    assert r.status == "matched" and r.request_id == b.request_id


def test_po_reference_to_someone_else_is_not_matched():
    r = evaluate(5000.0, [], [cand("9e085e38-e1a5-47e9-b8b4-588b3299e772", amount=5000.0, lines=[])], TOL, po_ref="PO-DEADBEEF")
    assert r.status == "no_match" and "PO-DEADBEEF" in r.issues[0]


def test_allocations_carry_the_tax_so_a_paid_invoice_clears_the_balance():
    po = cand(amount=3894.0, lines=[POLine(0, "Microsoft 365 E3 Seat License", 2, 1650.0)])
    r = evaluate(3894.0, [InvoiceLine("Microsoft 365 E3 Seat License", 2, 1650.0)], [po], TOL)
    assert r.status == "matched"
    assert sum(a["amount"] for a in r.allocations) == 3894.0
    assert r.remaining_after == 0
