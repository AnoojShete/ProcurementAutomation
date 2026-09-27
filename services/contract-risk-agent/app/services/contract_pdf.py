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
import hashlib
import io
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
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

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

    def party(role: str, name: str, signer: Optional[str]) -> list:
        if signed and signer:
            sig = Paragraph(
                f"<font name='Helvetica-Oblique' size='12'>{escape(signer)}</font><br/>"
                f"<font size='8' color='#59636e'>Electronically signed · {escape(_fmt_dt(c.signed_at))}</font>",
                st["cell"],
            )
        else:
            sig = Spacer(1, 26)
        return [
            Paragraph(f"<b>{escape(role)}</b>", st["cell"]),
            Paragraph(escape(name), st["cell_label"]),
            sig,
            Paragraph("Signature", st["small"]),
        ]

    # The platform (Subscriber/Purchaser side) signs through the e-sign
    # provider; the vendor's countersignature isn't tracked by this system.
    left = party("For the Company", "IT Procurement Intelligence Platform", c.signed_by)
    right = party("For the Vendor", c.vendor_name, None)
    # Middle spacer column keeps the two signature lines visibly separate.
    gap = 14 * mm
    rows = [[left[i], "", right[i]] for i in range(4)]
    t = Table(rows, colWidths=[(width - gap) / 2, gap, (width - gap) / 2], hAlign="LEFT", spaceBefore=6)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (0, 2), (0, 2), 0.75, INK),
        ("LINEBELOW", (2, 2), (2, 2), 0.75, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
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
        story.append(_kv_table(
            [
                ("Document", f"{_title_case(title)} (v{c.version})"),
                ("Contract ID", c.contract_id),
                ("Agreement SHA-256", text_sha256(c.contract_text)),
                ("Signed by", c.signed_by or "—"),
                ("Signed at", _fmt_dt(c.signed_at)),
                ("Signature provider", provider),
                ("Provider reference", c.esign_provider_ref or "—"),
            ],
            st, 40 * mm, mono_keys=frozenset({"Contract ID", "Agreement SHA-256", "Provider reference"}),
        ))
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
