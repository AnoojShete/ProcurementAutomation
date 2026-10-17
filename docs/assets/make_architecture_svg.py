"""Generates docs/assets/architecture.svg — every component and edge below
was checked against the repository (compose files, nginx.conf, acls.conf,
service code). Run: python docs/assets/make_architecture_svg.py docs/assets/architecture.svg"""
import sys
from html import escape

W, H = 1920, 1090
FONT = "Helvetica, Arial, sans-serif"
INK, MUTED, LINE = "#1f2937", "#4b5563", "#6b7280"
ML = "#6d28d9"  # AI/ML component text

C = {  # (fill, stroke) per layer
    "client": ("#f1f5f9", "#475569"),
    "gate": ("#ecfdf5", "#047857"),
    "svc": ("#eff6ff", "#1d4ed8"),
    "msg": ("#f5f3ff", "#6d28d9"),
    "data": ("#fffbeb", "#b45309"),
    "ext": ("#f9fafb", "#6b7280"),
    "obs": ("#f9fafb", "#6b7280"),
}

out = []
add = out.append


def text(x, y, s, size=12, weight="normal", fill=INK, anchor="start", italic=False):
    st = ' font-style="italic"' if italic else ""
    add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{st}>{escape(s)}</text>')


def box(x, y, w, h, kind, rx=8, dash=False, sw=1.4):
    f, s = C[kind]
    d = ' stroke-dasharray="5 4"' if dash else ""
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{f}" stroke="{s}" stroke-width="{sw}"{d}/>')


def path(d, marker_end=True, marker_start=False, dash=False, color=LINE, sw=1.5):
    m = (' marker-end="url(#arr)"' if marker_end else "") + (' marker-start="url(#arrs)"' if marker_start else "")
    da = ' stroke-dasharray="5 4"' if dash else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da}{m}/>')


def lines(x, y, items, size=11.5, gap=15.5):
    """items: str (normal), ("ml", str) for AI/ML, ("b", str) bold, ("m", str) muted."""
    for it in items:
        kind, s = it if isinstance(it, tuple) else ("n", it)
        fill = {"ml": ML, "m": MUTED}.get(kind, INK)
        weight = "bold" if kind == "b" else "normal"
        text(x, y, s, size=size, fill=fill, weight=weight)
        y += gap
    return y


def chip(cx, cy, label):
    add(f'<circle cx="{cx}" cy="{cy}" r="8.5" fill="#ffffff" stroke="{LINE}" stroke-width="1.2"/>')
    text(cx, cy + 4, label, size=11, weight="bold", anchor="middle", fill=INK)


add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    f'font-family="{FONT}">')
add('<defs>'
    f'<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker>'
    f'<marker id="arrs" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{LINE}"/></marker>'
    '</defs>')
add(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')

# ---------------------------------------------------------------- title
text(30, 36, "IT Procurement Intelligence Platform — system architecture", size=20, weight="bold")
text(30, 58, "Docker Compose deployment · verified against the repository (branch anjali, October 2026)",
     size=12.5, fill=MUTED)

# column geometry
MX0, MX1 = 290, 1550                 # main column
BW, STEP = 190, 214                  # service box width / pitch
xs = [MX0 + i * STEP for i in range(6)]

# ---------------------------------------------------------------- clients
box(MX0, 82, 940, 74, "client")
text(MX0 + 14, 104, "Web browser (and API clients) — React 18 + TypeScript SPA (Vite, Tailwind)", size=14, weight="bold")
lines(MX0 + 14, 124, [
    "Roles: requester · approver · finance · admin  (role-specific navigation; RoleGuard is UX only)",
    ("m", "Access token (JWT) in memory · refresh token in httpOnly cookie + CSRF header"),
], size=11.5)
box(MX0 + 970, 82, 290, 74, "client")
text(MX0 + 984, 104, "E-sign provider callback", size=14, weight="bold")
lines(MX0 + 984, 124, ["POST /api/webhooks/esign", ("m", "HMAC-SHA256, replay-protected")], size=11.5)

# ---------------------------------------------------------------- gateway
GY = 196
box(MX0, GY, MX1 - MX0, 58, "gate")
text(MX0 + 14, GY + 23, "nginx API gateway  :8080  (only public port)", size=14, weight="bold")
text(MX0 + 14, GY + 43, "Serves the built SPA · /api/<prefix> → service · rate limits on auth endpoints · "
     "CSP & security headers · 25 MB body cap · sets X-Correlation-ID", size=11.5, fill=MUTED)
path(f"M {MX0 + 410} 156 L {MX0 + 410} {GY - 2}")
text(MX0 + 418, 180, "HTTP: REST/JSON, Bearer JWT", size=11, fill=MUTED)
path(f"M {MX0 + 1110} 156 L {MX0 + 1110} {GY - 2}")
text(MX0 + 1118, 180, "HTTP POST", size=11, fill=MUTED)

# ---------------------------------------------------------------- services frame
FY0, FY1 = 300, 548
add(f'<rect x="{MX0 - 10}" y="{FY0}" width="{MX1 - MX0 + 20}" height="{FY1 - FY0}" rx="10" fill="none" '
    f'stroke="{C["svc"][1]}" stroke-width="1" stroke-dasharray="3 3"/>')
text(MX0 + 190, FY0 - 6, "APPLICATION SERVICES (FastAPI, Python 3.11) — each also listed with its gateway routes",
     size=11, weight="bold", fill=C["svc"][1])
path(f"M {MX0 + 40} {GY + 58} L {MX0 + 40} {FY0 - 2}")
text(MX0 + 48, GY + 80, "reverse proxy /api/*", size=11, fill=MUTED)

BY0, BY1 = 342, 538
svcs = [
    ("document-vendor-agent", ":8001  + worker", [
        "Upload → ClamAV scan → MinIO",
        ("ml", "OCR: pdfplumber · Docling ·"),
        ("ml", "  PaddleOCR · LayoutLMv3 check"),
        ("ml", "Classifier: TF-IDF + LogReg"),
        "Preprocess scans · review queue",
        "Fields · FX→INR · duplicates",
        "Vendor match · bank dual control",
        ("m", "/api/documents · /api/admin ·"),
        ("m", "/api/vendors/(onboard, payment…)"),
    ]),
    ("approval-inventory-agent", ":8002  + Temporal worker", [
        "Requests · spend tiers · SLA",
        "Authority & separation of duties",
        "Inventory · backorders · reorder",
        "Invoice ledger (3-way match)",
        ("ml", "Licence anomaly: IsolationForest"),
        ("ml", "  + SHAP reasons"),
        ("m", "/api/requests · inventory · licenses"),
        ("m", "authority · invoices · ops · orders"),
        ("m", "inbox · /email-action/*"),
    ]),
    ("chatbot-agent", ":8006", [
        "Assistant chat sessions",
        ("ml", "LLM via Ollama with 6"),
        ("ml", "  read-only tools"),
        "Calls agents' APIs with the",
        "  signed-in user's role",
        ("m", "/api/chat"),
    ]),
    ("contract-risk-agent", ":8003  + Temporal worker", [
        "Contracts (Jinja2 → text, PDF)",
        "Built-in e-sign, SHA-256 seal",
        ("ml", "Clauses: Legal-BERT (CUAD),"),
        ("ml", "  regex fallback"),
        ("ml", "Vendor risk: RandomForest"),
        "  + hard overrides, sanctions",
        "Renewal & drift (PSI) workflows",
        ("m", "/api/contracts · /api/vendors/*"),
        ("m", "/api/webhooks"),
    ]),
    ("notification-agent", ":8004", [
        "Consumes 11 event topics",
        "Urgent vs digest routing",
        "Jinja2 email templates",
        "Notification log",
        ("m", "Sends to Mailpit (dev)"),
        ("m", "/api/notifications"),
    ]),
    ("auth-service", ":8005", [
        "Sign-up · login · JWT (HS256)",
        "argon2id · lockout · CSRF",
        "Users & roles (admin)",
        "Business-rules engine",
        "  (47 rules, edited live)",
        ("m", "Serves GET /internal/business-"),
        ("m", "rules to every agent (5-min cache)"),
        ("m", "/api/auth · /api/admin/business-rules"),
    ]),
]
for (name, port, items), x in zip(svcs, xs):
    box(x, BY0, BW, BY1 - BY0, "svc")
    text(x + 10, BY0 + 19, name, size=12.5, weight="bold")
    text(x + 10, BY0 + 35, port, size=11, fill=C["svc"][1], weight="bold")
    add(f'<line x1="{x + 8}" y1="{BY0 + 43}" x2="{x + BW - 8}" y2="{BY0 + 43}" stroke="#bfdbfe"/>')
    lines(x + 10, BY0 + 60, items, size=11, gap=14.6)

doc, appr, chat, ctr, notif, auth = xs
MID = BY0 + 92
# adjacent synchronous calls (numbered, explained in the legend)
path(f"M {doc + BW} {MID} L {appr - 2} {MID}")
chip(doc + BW + 14, MID - 16, "1")
path(f"M {chat} {MID} L {appr + BW + 2} {MID}")
chip(appr + BW + 14, MID - 16, "2")
path(f"M {chat + BW} {MID} L {ctr - 2} {MID}")
chip(chat + BW + 14, MID - 16, "3")
# lane above the boxes: notification -> approval (mint email-approval link)
LY = 322
path(f"M {notif + 95} {BY0} L {notif + 95} {LY} L {appr + 120} {LY} L {appr + 120} {BY0 - 2}", dash=True)
text(appr + 134, LY - 6, "4  HTTP POST /internal/email-actions/mint (X-Internal-Service-Token)",
     size=11, fill=MUTED)

# ---------------------------------------------------------------- Temporal
TX0, TX1, TY0, TY1 = chat + 5, chat + BW - 5, 566, 618
box(TX0, TY0, TX1 - TX0, TY1 - TY0, "msg")
text(TX0 + 10, TY0 + 20, "Temporal  :7233", size=12.5, weight="bold")
text(TX0 + 10, TY0 + 38, "durable workflows & timers", size=10.8, fill=MUTED)
path(f"M {appr + BW - 30} {BY1} L {appr + BW - 30} {TY0 + 26} L {TX0 - 2} {TY0 + 26}", marker_start=True)
path(f"M {ctr + 30} {BY1} L {ctr + 30} {TY0 + 26} L {TX1 + 2} {TY0 + 26}", marker_start=True)
text(TX0 - 40, TY1 + 16, "gRPC: start/signal workflows; workers poll task queues", size=10.5, fill=MUTED)

# ---------------------------------------------------------------- Kafka
KY0, KY1 = 664, 744
box(MX0, KY0, MX1 - MX0, KY1 - KY0, "msg")
text(MX0 + 14, KY0 + 22, "Event backbone — Kafka API (Redpanda) · 17 topics · per-service SASL/SCRAM logins and ACLs",
     size=13.5, weight="bold")
lines(MX0 + 14, KY0 + 42, [
    ("m", "document.ingested (6 partitions) → worker · document.classified, vendor.matched → approval, contract, notification · "
          "approval.requested/decided → contract, notification, document"),
    ("m", "contract.generated/signed → approval, notification · invoice.matched → approval · risk.score.updated, "
          "contract.renewal.due, license.usage.updated, vendor.* → notification · business_rule.updated → agents"),
], size=10.8, gap=15)
# connectors: publish via transactional outbox (down), consume via deliver() (up)
for x, both in ((doc + 40, True), (appr + 32, True), (ctr + BW - 30, True), (notif + 50, False), (auth + 95, False)):
    if x == notif + 50:          # consume only
        path(f"M {x} {KY0} L {x} {BY1 + 2}")
    elif x == auth + 95:          # publish only
        path(f"M {x} {BY1} L {x} {KY0 - 2}")
    else:
        path(f"M {x} {BY1 + 2} L {x} {KY0 - 2}", marker_start=True)
text(doc + 46, BY1 + 40, "outbox ↓ / deliver() ↑", size=10.5, fill=MUTED)

# ---------------------------------------------------------------- data layer
DY0, DY1 = 800, 896
text(MX0, DY0 - 10, "DATA LAYER", size=11, weight="bold", fill=C["data"][1])
data = [
    (MX0, 380, "PostgreSQL 16 — one shared database", [
        "Business tables · audit_log · auth_users · business_rules",
        "event_outbox/inbox/dlq · event_log · Temporal's store",
        ("m", "Each service migrates its own tables"),
    ]),
    (MX0 + 393, 270, "Redis 7", [
        "Idempotency-Key responses (24 h)",
        "Inventory reservation locks",
        ("m", "No persistence (cache only)"),
    ]),
    (MX0 + 676, 270, "MinIO (S3 API)", [
        "Bucket documents/<id>/<file>",
        "Original uploads",
        ("m", "document-vendor-agent only"),
    ]),
    (MX0 + 959, 301, "Models & ML tracking", [
        ("ml", "Artifacts trained at image build"),
        ("ml", "hf-cache: LayoutLMv3, Legal-BERT"),
        ("m", "Sanctions index volume · MLflow :5050"),
    ]),
]
for x, w, title, items in data:
    box(x, DY0, w, DY1 - DY0, "data")
    text(x + 12, DY0 + 21, title, size=12.5, weight="bold")
    lines(x + 12, DY0 + 41, items, size=10.8, gap=15)
# services -> PostgreSQL along the left margin (outside the Kafka bar)
path(f"M {MX0 - 10} 520 L 262 520 L 262 {DY0 + 48} L {MX0 - 2} {DY0 + 48}")
add(f'<text x="252" y="{(520 + DY0) // 2 + 40}" font-size="11" fill="{MUTED}" text-anchor="middle" '
    f'transform="rotate(-90 252 {(520 + DY0) // 2 + 40})">SQL (SQLAlchemy async) — all six services</text>')

# ---------------------------------------------------------------- inputs (left)
IX0, IW = 30, 210
text(IX0, 336, "DOCUMENT INPUTS", size=11, weight="bold", fill=C["client"][1])
box(IX0, 346, IW, 62, "client")
text(IX0 + 10, 366, "Drop folder ./inbox", size=12.5, weight="bold")
lines(IX0 + 10, 384, [("m", "polled every 3 s by the worker;"), ("m", "→ processed/ or failed/")], size=10.6, gap=14)
box(IX0, 424, IW, 62, "client")
text(IX0 + 10, 444, "Intake mailbox", size=12.5, weight="bold")
lines(IX0 + 10, 462, [("m", "POP3/IMAP, read-only, every 30 s"), ("m", "(Mailpit in development)")], size=10.6, gap=14)
path(f"M {IX0 + IW} 377 L {doc - 2} 377")
path(f"M {IX0 + IW} 455 L {doc - 2} 455")
text(IX0 + IW + 6, 371, "files", size=10.5, fill=MUTED)
text(IX0 + IW + 6, 449, "mail", size=10.5, fill=MUTED)

# ---------------------------------------------------------------- external (right)
EX0, EW = 1600, 290
text(EX0, 286, "SUPPORTING & EXTERNAL SERVICES", size=11, weight="bold", fill=C["ext"][1])
box(EX0, 296, EW, 448, "ext")
ext = [
    ("ClamAV (clamd :3310)", "INSTREAM scan of every upload; fails closed", "document-vendor"),
    ("Mailpit / SMTP", "outgoing mail (dev | smtp) · POP3 intake", "auth, notification, doc worker"),
    ("Ollama LLM (host :11434)", "/api/chat with tool calling", "chatbot"),
    ("Frankfurter (ECB rates)", "currency → INR, rate stored once", "document-vendor"),
    ("Razorpay IFSC · gstincheck.co.in", "bank code lookup · GSTIN (quota-gated)", "document-vendor"),
    ("HaveIBeenPwned range API", "breached-password check (k-anonymity)", "auth"),
    ("OpenSanctions list", "downloaded on demand, refreshed daily", "contract-risk"),
]
y = 322
for name, what, who in ext:
    text(EX0 + 12, y, name, size=12, weight="bold")
    text(EX0 + 12, y + 16, what, size=10.6, fill=MUTED)
    text(EX0 + 12, y + 31, "used by: " + who, size=10.6, fill=C["svc"][1])
    y += 60
path(f"M {MX1 + 10} 340 L {EX0 - 2} 340")
text(MX1 + 13, 333, "HTTP", size=10, fill=MUTED)

# ---------------------------------------------------------------- observability
OY0 = 800
box(EX0, OY0, EW, 96, "obs")
text(EX0 + 12, OY0 + 21, "Observability", size=12.5, weight="bold")
lines(EX0 + 12, OY0 + 41, [
    "Prometheus ← /metrics, kafka-exporter",
    "Promtail → Loki → Grafana (logs by",
    "  correlation id) · Temporal UI :8088",
], size=10.6, gap=15)
path(f"M {MX1 + 10} 520 L 1578 520 L 1578 {OY0 + 48} L {EX0 - 2} {OY0 + 48}", dash=True)
add(f'<text x="1570" y="660" font-size="10.5" fill="{MUTED}" text-anchor="middle" '
    f'transform="rotate(-90 1570 660)">metrics scrape · container logs</text>')

# ---------------------------------------------------------------- legend
LY0 = 930
add(f'<line x1="30" y1="{LY0 - 14}" x2="{W - 30}" y2="{LY0 - 14}" stroke="#e5e7eb"/>')
text(30, LY0 + 4, "Service-to-service calls (synchronous HTTP inside the Docker network)", size=12, weight="bold")
calls = [
    ("1", "document-vendor worker → approval-inventory: POST /invoices/match (books the invoice; service JWT)"),
    ("2", "chatbot → approval-inventory: GET /orders/summary/latest, /requests, /licenses/anomaly-summary"),
    ("3", "chatbot → contract-risk: GET /vendors/, /vendors/{id}/risk  (2 and 3 use a JWT minted for the user)"),
    ("4", "notification → approval-inventory: mint a single-use email-approval link"),
]
y = LY0 + 28
for n, s in calls:
    chip(42, y - 4, n)
    text(58, y, s, size=11.5)
    y += 22
lx = 1100
text(lx, LY0 + 4, "Key", size=12, weight="bold")
legend = [("svc", "Application service"), ("msg", "Messaging / orchestration"), ("data", "Data store"),
          ("ext", "Supporting, external, observability"), ("gate", "Gateway"), ("client", "Client / input")]
for i, (k, label) in enumerate(legend):
    cx, cy = lx + (i % 2) * 230, LY0 + 18 + (i // 2) * 22
    f, s = C[k]
    add(f'<rect x="{cx}" y="{cy}" width="22" height="14" rx="3" fill="{f}" stroke="{s}" stroke-width="1.3"/>')
    text(cx + 30, cy + 11, label, size=11.5)
ky = LY0 + 18 + 3 * 22
text(lx, ky + 11, "Purple text = AI/ML component", size=11.5, fill=ML)
add(f'<line x1="{lx + 230}" y1="{ky + 7}" x2="{lx + 262}" y2="{ky + 7}" stroke="{LINE}" stroke-width="1.5" '
    f'stroke-dasharray="5 4" marker-end="url(#arr)"/>')
text(lx + 270, ky + 11, "dashed = token-authenticated or telemetry", size=11.5)

add("</svg>")
open(sys.argv[1], "w").write("\n".join(out))
print("written", sys.argv[1])
