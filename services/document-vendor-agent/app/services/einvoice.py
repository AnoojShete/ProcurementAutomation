"""E-invoice QR check (feature expansion Phase 4).

An Indian e-invoice carries a QR code that the Invoice Registration Portal
(IRP) signs: a JWT (RS256) whose `data` claim holds the seller and buyer
GSTIN, invoice number, date, total value, item count, main HSN code and the
IRN. This module finds the QR on the document, verifies the signature
offline with the portal's public key and compares the signed values with
what was read from the printed invoice, so an altered total or a forged
QR is caught without calling any external service.

The key: EINVOICE_PUBLIC_KEY (PEM text) or EINVOICE_PUBLIC_KEY_FILE (a path),
the IRP's published key, in production.
In development only, the demo key in shared/einvoice/ is used; its private
half is in data/einvoice-demo/ so test invoices can be signed. Production
never trusts the demo key, since anyone can sign with it.
"""
import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Optional

import jwt

from shared.money import inr
from shared.runtime_env import is_development

logger = logging.getLogger(__name__)

DEMO_KEY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "shared", "einvoice", "demo-irp-public-key.pem")
_JWT_SHAPE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


@dataclass
class EinvoiceResult:
    present: bool = False
    verified: Optional[bool] = None          # signature valid (None: not checked)
    mismatches: list = field(default_factory=list)
    claims: dict = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _demo_key_path() -> str:
    # The service image has shared/ at /app/shared; the repo has it two levels up.
    for path in ("/app/shared/einvoice/demo-irp-public-key.pem", DEMO_KEY_FILE):
        if os.path.exists(path):
            return path
    return DEMO_KEY_FILE


@lru_cache(maxsize=1)
def public_key() -> Optional[str]:
    text_key = os.environ.get("EINVOICE_PUBLIC_KEY", "").strip().replace("\\n", "\n")
    path = os.environ.get("EINVOICE_PUBLIC_KEY_FILE", "").strip()
    demo = open(_demo_key_path()).read() if os.path.exists(_demo_key_path()) else None
    if text_key or path:
        key = text_key or open(path).read()
        if demo and key.strip() == demo.strip() and not is_development():
            logger.error("EINVOICE_PUBLIC_KEY is the published demo key; e-invoice QRs won't be verified")
            return None
        return key
    return demo if is_development() else None


# ── finding the QR ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _wechat():
    import cv2
    return cv2.wechat_qrcode_WeChatQRCode()


def _decode_array(gray) -> list[str]:
    import cv2
    found = []
    try:
        found, _ = _wechat().detectAndDecode(gray)
        found = list(found)
    except Exception:
        found = []
    if not found:
        value, _, _ = cv2.QRCodeDetector().detectAndDecode(gray)
        found = [value] if value else []
    return found


_EINVOICE_HINT = re.compile(r"\b(?:IRN|Ack(?:nowledgement)?\.?\s*(?:No|Number|Date)|e-?invoice)\b", re.I)


def looks_like_einvoice(text: str) -> bool:
    """An e-invoice prints its IRN / acknowledgement next to the QR. Searching
    every document for a QR costs ~1.5 s (digital) to ~10 s (scan), more than
    the rest of the pipeline, so the tax stage only looks when this says so
    (or when the supplier must issue e-invoices)."""
    return bool(_EINVOICE_HINT.search(text or ""))


def _pages(data: bytes, file_type: str, max_pages: int = 2, scale: float = 4):
    import numpy as np
    if file_type == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        for i in range(min(len(pdf), max_pages)):
            yield np.array(pdf[i].render(scale=scale).to_pil().convert("L"))
    else:
        import io
        from PIL import Image
        yield np.array(Image.open(io.BytesIO(data)).convert("L"))


def find_qr_token(data: bytes, file_type: str) -> Optional[str]:
    """The signed QR payload (a JWT) on the document, or None. Never raises:
    a document whose QR can't be read is treated as having none."""
    try:
        # A clear QR decodes at 2x; 4x only for small or blurred ones (images aren't re-rendered).
        for scale in ((2, 4) if file_type == "pdf" else (1,)):
            for page in _pages(data, file_type, scale=scale):
                for value in _decode_array(page):
                    if _JWT_SHAPE.match(value.strip()):
                        return value.strip()
    except Exception as e:
        logger.warning(f"e-invoice QR scan failed (treated as no QR): {e}")
    return None


# ── verifying it ─────────────────────────────────────────────────────────────

def _norm_number(value) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def verify(token: str, *, supplier_gstin: Optional[str], buyer_gstin: Optional[str], invoice_number: Optional[str],
           total: Optional[float], irn: Optional[str], key: Optional[str] = None,
           tolerance: float = 1.0) -> EinvoiceResult:
    """Signature first; then each signed value against the printed one."""
    result = EinvoiceResult(present=True)
    key = key if key is not None else public_key()
    if not key:
        result.error = "no IRP public key configured (EINVOICE_PUBLIC_KEY); the QR can't be verified"
        return result
    try:
        claims = jwt.decode(token, key, algorithms=["RS256"], options={"verify_aud": False, "verify_exp": False})
    except jwt.InvalidTokenError as e:
        result.verified = False
        result.error = f"signature check failed: {e}"
        return result
    data = claims.get("data")
    try:
        data = json.loads(data) if isinstance(data, str) else (data or {})
    except ValueError:
        data = {}
    result.verified = True
    result.claims = data
    checks = [
        ("seller GSTIN", data.get("SellerGstin"), supplier_gstin, lambda a, b: a.upper() == b.upper()),
        ("buyer GSTIN", data.get("BuyerGstin"), buyer_gstin, lambda a, b: a.upper() == b.upper()),
        ("invoice number", data.get("DocNo"), invoice_number, lambda a, b: _norm_number(a) == _norm_number(b)),
        ("total value", data.get("TotInvVal"), total, lambda a, b: abs(float(a) - float(b)) <= tolerance),
        ("IRN", data.get("Irn"), irn, lambda a, b: a.lower() == b.lower()),
    ]
    for label, signed, printed, same in checks:
        if signed in (None, "") or printed in (None, ""):
            continue
        try:
            ok = same(signed, printed)
        except (TypeError, ValueError):
            ok = False
        if not ok:
            if label == "total value":
                signed, printed = inr(float(signed)), inr(float(printed))
            result.mismatches.append(f"{label}: the signed QR says {signed}, the invoice shows {printed}")
    return result
