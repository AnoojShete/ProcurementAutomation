"""Renders a contract as a PDF.

Two variants from the same stored contract_text:
  - the working copy (GET /contracts/{id}/document): the agreement with an
    empty signature block, watermarked DRAFT until it's sent for signature;
  - the signed copy (GET /contracts/{id}/signed-document): the agreement
    with the signature block filled in, plus a certificate-of-completion
    page — signer, time, provider reference, a SHA-256 of the agreement
    text, and the contract's audit trail.

When a live Documenso instance signed the contract, the signed copy comes
from Documenso instead (see esign_client.download_signed_pdf) and this
module is only the fallback.
"""
import base64
import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

logger = logging.getLogger(__name__)

INK = colors.HexColor("#1f2328")
MUTED = colors.HexColor("#59636e")
RULE = colors.HexColor("#d1d9e0")
SHADE = colors.HexColor("#f6f8fa")

_SECTION_RE = re.compile(r"^\d+\.\s+\S")
# Header lines the templates print that the PDF's metadata table already shows.
_DUPLICATE_HEADER_RE = re.compile(r"^(Contract ID|Generated):", re.IGNORECASE)
_ACRONYMS = {"Saas": "SaaS", "It": "IT", "Sla": "SLA"}


def _title_case(text: str) -> str:
    return " ".join(_ACRONYMS.get(w, w) for w in text.title().split(" "))
_SIGNATURE_HEADING_RE = re.compile(r"^\d+\.\s+SIGNATURES\s*$", re.IGNORECASE)


@dataclass
class AuditEntry:
    at: Optional[datetime]
    action: str
    detail: str = ""


@dataclass
class ContractPdfInput:
    contract_id: str
    contract_text: str
    status: str
    version: int
    template: Optional[str]
    vendor_name: str
    generated_at: Optional[datetime]
    signed_at: Optional[datetime] = None
    signed_by: Optional[str] = None
    esign_provider_ref: Optional[str] = None
    audit_trail: list[AuditEntry] = field(default_factory=list)
    signature_image: Optional[str] = None
    signer_designation: Optional[str] = None
    signature_method: Optional[str] = None
    approval_channel: Optional[str] = None
    bulk_batch_id: Optional[str] = None
    mandate_id: Optional[str] = None
    mandate_text_hash: Optional[str] = None


def _decode_signature_image(data_url: Optional[str], width: float = 48 * mm, height: float = 14 * mm) -> Optional[RLImage]:
    """Decode a base64 PNG data URL into a ReportLab Image flowable."""
    if not data_url or not isinstance(data_url, str):
        return None
    try:
        if "," in data_url:
            _, b64_data = data_url.split(",", 1)
        else:
            b64_data = data_url
        img_bytes = base64.b64decode(b64_data)
        buf = io.BytesIO(img_bytes)
        img = RLImage(buf, width=width, height=height)
        img.hAlign = "LEFT"
        return img
    except Exception as e:
        logger.warning("Could not decode signature image: %s", e)
        return None


def text_sha256(contract_text: str) -> str:
    return hashlib.sha256((contract_text or "").encode("utf-8")).hexdigest()


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=10, leading=14.5, textColor=INK, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", parent=base, fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=9, textColor=MUTED),
        "section": ParagraphStyle("section", parent=base, fontName="Helvetica-Bold", fontSize=10.5, spaceBefore=10, spaceAfter=3),
        "body": base,
        "indent": ParagraphStyle("indent", parent=base, leftIndent=14),
        "bullet": ParagraphStyle("bullet", parent=base, leftIndent=26, firstLineIndent=-10),
        "small": ParagraphStyle("small", parent=base, fontSize=8.5, leading=12, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=12.5),
        "cell_label": ParagraphStyle("cell_label", parent=base, fontSize=9, leading=12.5, textColor=MUTED),
        "mono": ParagraphStyle("mono", parent=base, fontName="Courier", fontSize=8.5, leading=12),
    }


def _fmt_dt(value: Optional[datetime]) -> str:
    if value is None:
        return "—"
    return value.strftime("%d %b %Y, %H:%M UTC") if value.tzinfo else value.strftime("%d %b %Y, %H:%M")


def _split_text(contract_text: str) -> tuple[str, list[str]]:
    """First non-empty line is the agreement title. The template's own
    SIGNATURES section (blank underscore lines) is dropped — the PDF draws
    a real signature block instead."""
    lines = (contract_text or "").splitlines()
    title = ""
    body: list[str] = []
    skipping_signatures = False
    for line in lines:
        if not title and line.strip():
            title = line.strip()
            continue
        if _SIGNATURE_HEADING_RE.match(line.strip()):
            skipping_signatures = True
            continue
        if skipping_signatures:
            if _SECTION_RE.match(line.strip()):
                skipping_signatures = False
            else:
                continue
        if _DUPLICATE_HEADER_RE.match(line.strip()):
            continue
        body.append(line)
    while body and not body[0].strip():
        body.pop(0)
    return title or "Agreement", body


def _body_flowables(lines: list[str], st: dict) -> list:
    out: list = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            out.append(Spacer(1, 4))
        elif _SECTION_RE.match(stripped):
            out.append(Paragraph(escape(stripped), st["section"]))
        elif stripped.startswith("- "):
            out.append(Paragraph("•&nbsp;&nbsp;" + escape(stripped[2:]), st["bullet"]))
        elif line.startswith(" "):
            out.append(Paragraph(escape(stripped), st["indent"]))
        else:
            out.append(Paragraph(escape(stripped), st["body"]))
    return out


def _kv_table(rows: list[tuple[str, str]], st: dict, label_width: float, mono_keys: frozenset = frozenset()) -> Table:
    data = [
        [Paragraph(escape(k), st["cell_label"]), Paragraph(escape(v), st["mono"] if k in mono_keys else st["cell"])]
        for k, v in rows
    ]
    t = Table(data, colWidths=[label_width, None], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return t


def _signature_block(c: ContractPdfInput, st: dict, width: float) -> Table:
    signed = c.status == "signed"

    signer_name = ""
    if c.signed_by:
        signer_name = c.signed_by.split("<")[0].strip() if "<" in c.signed_by else c.signed_by.strip()

    sig_img = _decode_signature_image(c.signature_image, width=48 * mm, height=14 * mm) if signed else None
    if signed and c.signed_by:
        if sig_img is not None:
            left_sig = sig_img
        else:
            left_sig = Paragraph(
                f"<font name='Helvetica-Oblique' size='12'>{escape(signer_name)}</font>",
                st["cell"],
            )
        left_sub = [
            Paragraph("Signature", st["small"]),
            Paragraph(f"<b>Name:</b> {escape(signer_name)}", st["cell"]),
        ]
        if c.signer_designation:
            left_sub.append(Paragraph(f"<b>Designation:</b> {escape(c.signer_designation)}", st["cell"]))
        left_sub.append(
            Paragraph(
                f"<font size='8' color='#59636e'>Electronically signed · {escape(_fmt_dt(c.signed_at))}</font>",
                st["small"],
            )
        )
        # Prompt 10 Section 2.3: Channel label & auto-signed mandate label
        if c.approval_channel:
            channel_label = "Approved through email link" if c.approval_channel == "email" else "Approved in the application"
            left_sub.append(
                Paragraph(
                    f"<font size='8' color='#59636e'>{escape(channel_label)}</font>",
                    st["small"],
                )
            )
        if c.signature_method == "auto_mandate" or c.mandate_id:
            mandate_short = str(c.mandate_id)[:8] if c.mandate_id else "—"
            batch_short = str(c.bulk_batch_id)[:8] if c.bulk_batch_id else ""
            batch_txt = f" (batch {escape(batch_short)})" if batch_short else ""
            left_sub.append(
                Paragraph(
                    f"<font size='8' color='#59636e'>Approved and signed under signing mandate {escape(mandate_short)}{batch_txt}</font>",
                    st["small"],
                )
            )
    else:
        left_sig = Spacer(1, 26)
        left_sub = [Paragraph("Signature", st["small"])]

    right_sig = Spacer(1, 26)
    right_sub = [Paragraph("Signature", st["small"])]

    gap = 14 * mm
    col_w = (width - gap) / 2
    rows = [
        [Paragraph("<b>For the Company</b>", st["cell"]), "", Paragraph("<b>For the Vendor</b>", st["cell"])],
        [Paragraph("IT Procurement Intelligence Platform", st["cell_label"]), "", Paragraph(escape(c.vendor_name), st["cell_label"])],
        [left_sig, "", right_sig],
        [left_sub, "", right_sub],
    ]
    t = Table(rows, colWidths=[col_w, gap, col_w], hAlign="LEFT", spaceBefore=6)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("VALIGN", (0, 2), (-1, 2), "BOTTOM"),
        ("LINEBELOW", (0, 2), (0, 2), 0.75, INK),
        ("LINEBELOW", (2, 2), (2, 2), 0.75, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 2), (-1, 2), 4),
    ]))
    return t


def render_contract_pdf(c: ContractPdfInput, include_certificate: bool = False) -> bytes:
    buf = io.BytesIO()
    st = _styles()
    title, body_lines = _split_text(c.contract_text)
    short_id = c.contract_id[:8]
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm, topMargin=20 * mm, bottomMargin=20 * mm,
        title=f"{_title_case(title)} — {c.vendor_name}", author="IT Procurement Intelligence Platform",
        subject=f"Contract {c.contract_id}",
    )
    # The page frame pads 6pt on each side inside doc.width.
    width = doc.width - 12

    status_label = {"draft": "Draft", "pending_signature": "Awaiting signature", "signed": "Signed"}.get(
        c.status, c.status.replace("_", " ").title()
    )
    story: list = [
        Paragraph(escape(_title_case(title)), st["title"]),
        Paragraph(f"{escape(c.vendor_name)} · Contract {escape(short_id)} · Version {c.version}", st["subtitle"]),
        Spacer(1, 10),
        _kv_table(
            [
                ("Contract ID", c.contract_id),
                ("Vendor", c.vendor_name),
                ("Template", _title_case((c.template or "—").replace("_", " "))),
                ("Status", status_label),
                ("Generated", _fmt_dt(c.generated_at)),
            ],
            st, 32 * mm, mono_keys=frozenset({"Contract ID"}),
        ),
        Spacer(1, 8),
    ]
    story += _body_flowables(body_lines, st)
    story.append(Spacer(1, 12))
    story.append(KeepTogether([Paragraph("Signatures", st["section"]), _signature_block(c, st, width)]))

    if include_certificate:
        story += [PageBreak(), Paragraph("Certificate of Completion", st["title"]),
                  Paragraph("Issued by the IT Procurement Intelligence Platform for the agreement above.", st["subtitle"]),
                  Spacer(1, 10)]
        provider = (c.esign_provider_ref or "").split("-", 1)[0].title() or "—"
        cert_rows = [
            ("Document", f"{_title_case(title)} (v{c.version})"),
            ("Contract ID", c.contract_id),
            ("Agreement SHA-256", text_sha256(c.contract_text)),
            ("Signed by", c.signed_by or "—"),
        ]
        if c.signer_designation:
            cert_rows.append(("Designation", c.signer_designation))
        cert_rows.extend([
            ("Signed at", _fmt_dt(c.signed_at)),
            ("Signature provider", provider),
            ("Provider reference", c.esign_provider_ref or "—"),
        ])
        if c.approval_channel:
            channel_label = "Approved through email link" if c.approval_channel == "email" else "Approved in the application"
            cert_rows.append(("Approval channel", channel_label))

        is_auto_mandate = c.signature_method == "auto_mandate" or bool(c.mandate_id)
        if is_auto_mandate:
            mandate_short = str(c.mandate_id)[:8] if c.mandate_id else "—"
            batch_short = str(c.bulk_batch_id)[:8] if c.bulk_batch_id else "—"
            cert_rows.extend([
                ("Signing method", "Automatic under signing mandate"),
                ("Mandate ID", str(c.mandate_id or "—")),
                ("Mandate short ID", mandate_short),
                ("Mandate text SHA-256", str(c.mandate_text_hash or "—")),
                ("Approval batch ID", str(c.bulk_batch_id or "—")),
            ])

        story.append(_kv_table(
            cert_rows,
            st, 40 * mm, mono_keys=frozenset({"Contract ID", "Agreement SHA-256", "Provider reference", "Mandate ID", "Mandate text SHA-256", "Approval batch ID"}),
        ))
        if is_auto_mandate:
            story += [
                Spacer(1, 6),
                Paragraph(
                    "<b>Disclaimer:</b> Signature applied automatically under a standing mandate; not individually reviewed at signing.",
                    st["small"],
                ),
            ]
        if c.signature_image:
            cert_img = _decode_signature_image(c.signature_image, width=48 * mm, height=14 * mm)
            if cert_img:
                story += [
                    Spacer(1, 8),
                    Paragraph("Signature Mark", st["section"]),
                    cert_img,
                ]
        if c.audit_trail:
            story += [Spacer(1, 14), Paragraph("Audit trail", st["section"])]
            rows = [[Paragraph("<b>Time</b>", st["cell"]), Paragraph("<b>Event</b>", st["cell"]),
                     Paragraph("<b>Detail</b>", st["cell"])]]
            for e in c.audit_trail:
                rows.append([
                    Paragraph(escape(_fmt_dt(e.at)), st["cell"]),
                    Paragraph(escape(e.action.replace("_", " ").capitalize()), st["cell"]),
                    Paragraph(escape(e.detail), st["cell_label"]),
                ])
            t = Table(rows, colWidths=[42 * mm, 42 * mm, None], hAlign="LEFT", repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t)
        story += [Spacer(1, 14), Paragraph(
            "The SHA-256 above is computed over the agreement text as generated. Recomputing it over the "
            "stored contract text and getting the same value shows the text has not changed since signing.",
            st["small"],
        )]

    watermark = "DRAFT" if c.status == "draft" else None
    footer_right = "Signed copy" if include_certificate else status_label

    def on_page(canvas, _doc):
        canvas.saveState()
        if watermark:
            canvas.setFillColor(colors.Color(0.55, 0.58, 0.62, alpha=0.12))
            canvas.setFont("Helvetica-Bold", 96)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, -30, watermark)
            canvas.rotate(-35)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setStrokeColor(RULE)
        canvas.setLineWidth(0.5)
        canvas.line(22 * mm, 14 * mm, A4[0] - 22 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(22 * mm, 10 * mm, f"Contract {c.contract_id} · v{c.version} · {footer_right}")
        canvas.drawRightString(A4[0] - 22 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
