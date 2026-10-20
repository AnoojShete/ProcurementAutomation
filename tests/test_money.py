"""shared/money.inr: rupee amounts in lakh grouping, as the GST and TDS
messages show them (feature expansion Phase 4)."""
import pytest

from shared.money import inr


@pytest.mark.parametrize("amount,decimals,text", [
    (0, 2, "₹0.00"), (999, 2, "₹999.00"), (1000, 2, "₹1,000.00"), (118000, 2, "₹1,18,000.00"),
    (1234567.5, 2, "₹12,34,567.50"), (50_000_000, 0, "₹5,00,00,000"), (-2000, 0, "-₹2,000"), (None, 2, "—"),
])
def test_lakh_grouping(amount, decimals, text):
    assert inr(amount, decimals) == text
