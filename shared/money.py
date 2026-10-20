"""Rupee amounts as Indians write them: ₹1,18,000.00 (lakh grouping)."""
from typing import Optional


def inr(amount: Optional[float], decimals: int = 2) -> str:
    if amount is None:
        return "—"
    sign = "-" if amount < 0 else ""
    whole, _, frac = f"{abs(amount):.{decimals}f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    text = ",".join(groups + [tail]) if groups else tail
    return f"{sign}₹{text}" + (f".{frac}" if decimals else "")
