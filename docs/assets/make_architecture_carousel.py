"""Generates the two-slide architecture diagram: docs/assets/architecture-1.svg
(browser, gateway and the six agents) and architecture-2.svg (how the agents
talk and where data lives). The MkDocs page System architecture shows them as
a carousel (inlined with pymdownx.snippets); the Slides tab in
docs/presentation.html carries the same SVGs between <!-- arch:N --> markers,
which this script refreshes. The full single-page diagram for print is still
make_architecture_svg.py.

Every box is a clickable node: it lights up what it connects to and shows its
role in the caption under the diagram (docs/guide/javascripts/architecture.js,
and the deck's own script). Colour means "one agent"; infrastructure is neutral.

    python docs/assets/make_architecture_carousel.py
"""
import os
import re
import sys
from html import escape

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
W, H = 1440, 780

ICONS = {  # 24-unit stroke icons
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "pen": '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
    "shield": '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
    "doc": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "approve": '<circle cx="12" cy="12" r="9"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "contract": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>'
                '<path d="M8 17c1.5-2.5 2.5-2.5 3 0s1.5 1 3-1"/>',
    "bell": '<path d="M6 16v-5a6 6 0 0 1 12 0v5l2 2H4z"/><path d="M10 20a2 2 0 0 0 4 0"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M15 8l2 2"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "zap": '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "db": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9c-2.5-2.5-3.5-5.5-3.5-9s1-6.5 3.5-9z"/>',
    "pulse": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
}

# The six agents: id, colour class, short name, two-line name, port, gateway route, two lines, AI inside, icon
AGENTS = [
    ("doc", "Document", ("Document", "& Vendor"), ":8001 + worker", "/api/documents",
     ("Reads documents", "Checks vendors"), True, "doc",
     "takes documents in, virus-scans and reads them (OCR, classifier, LayoutLMv3), extracts and checks the fields, "
     "matches the vendor."),
    ("appr", "Approval", ("Approval", "& Inventory"), ":8002 + worker", "/api/requests",
     ("Approvals, budgets", "Stock, licences"), True, "approve",
     "turns a quote into a purchase request, routes it by amount, enforces who may approve, keeps budgets, stock, "
     "licences (anomaly model) and the invoice ledger."),
    ("ctr", "Contract", ("Contract", "& Risk"), ":8003 + worker", "/api/contracts",
     ("Contracts, e-sign", "Vendor risk"), True, "contract",
     "writes the contract after the final approval, collects the e-signature, reads clauses (Legal-BERT) and scores "
     "vendor risk; a sanctioned vendor can't be signed."),
    ("notif", "Notification", ("Notification", "agent"), ":8004", "/api/notifications",
     ("Emails each step", "Editable templates"), False, "bell",
     "listens to 17 event topics and emails whoever must act next, from templates admins edit in the Control Panel."),
    ("auth", "Auth", ("Auth", "service"), ":8005", "/api/auth",
     ("Accounts, roles", "Business rules"), False, "key",
     "sign-up, login and roles; serves the business rules every agent reads, changed live without a deploy."),
    ("chat", "Assistant", ("Assistant", "(chatbot)"), ":8006", "/api/chat",
     ("Answers questions", "Checks access"), True, "chat",
     "answers questions from contracts, documents and records (retrieval-augmented, local LLM), only from what the "
     "signed-in user may see."),
]
AGENT = {a[0]: a for a in AGENTS}

STYLE = """
.arch{--ink:var(--arch-ink,#14213d);--ink2:var(--arch-ink2,#3f4a5a);--ink3:var(--arch-ink3,#5d6670);
--sheet:var(--arch-sheet,#ffffff);--paper:var(--arch-paper,#f4f5f1);--rule:var(--arch-rule,#d5dad2);
--gate:var(--arch-gate,#14213d);--ongate:var(--arch-ongate,#f5f6f2);--ongate2:var(--arch-ongate2,#c9d3e3);
font-family:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif}
.arch .c-doc{--c:var(--arch-doc,#c2410c)}.arch .c-appr{--c:var(--arch-appr,#1d4ed8)}
.arch .c-ctr{--c:var(--arch-ctr,#be185d)}.arch .c-notif{--c:var(--arch-notif,#15803d)}
.arch .c-auth{--c:var(--arch-auth,#6d28d9)}.arch .c-chat{--c:var(--arch-chat,#0f766e)}
.arch .c-infra{--c:var(--ink)}
.arch text{fill:var(--ink)}.arch .t2{fill:var(--ink2)}.arch .t3{fill:var(--ink3)}.arch .tc{fill:var(--c)}
.arch .b{font-weight:600}.arch .mono{font-family:'IBM Plex Mono',ui-monospace,Menlo,monospace}
.arch .box{fill:var(--sheet);stroke:var(--rule);stroke-width:1.5}
.arch .soft{fill:var(--paper);stroke:var(--rule);stroke-width:1.5}
.arch .ext{fill:var(--sheet);stroke:var(--ink3);stroke-width:1.5;stroke-dasharray:6 5}
.arch .band{fill:var(--c)}.arch .tint{fill:var(--c);fill-opacity:.12}
.arch .gate{fill:var(--gate)}.arch .gate-t{fill:var(--ongate)}.arch .gate-t2{fill:var(--ongate2)}
.arch .ico{fill:none;stroke:var(--c);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.arch .ico-l{fill:none;stroke:var(--ongate);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.arch .ai{fill:var(--c)}.arch .ai-t{fill:var(--sheet);font-weight:700}
.arch .edge{fill:none;stroke:var(--ink3);stroke-width:2.2}
.arch .edge-head{fill:var(--ink3)}
.arch .node{cursor:pointer;outline:none}
.arch .node:focus-visible .box,.arch .node:focus-visible .soft,.arch .node:focus-visible .ext{stroke:var(--c);stroke-width:3}
.arch [data-links]{transition:opacity .2s}
.arch.focus [data-links]:not(.on){opacity:.16}
.arch .node.on .box,.arch .node.on .soft,.arch .node.on .ext{stroke:var(--c);stroke-width:3}
.arch .edge-g.on .edge{stroke:var(--ink);stroke-width:3}.arch .edge-g.on .edge-head{fill:var(--ink)}
"""


class Svg:
    def __init__(self, label):
        self.out = []
        self.label = label

    def add(self, s):
        self.out.append(s)

    def text(self, x, y, s, size=18, cls="", anchor="start"):
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        c = f' class="{cls}"' if cls else ""
        self.add(f'<text x="{x}" y="{y}" font-size="{size}"{c}{a}>{escape(s)}</text>')

    def icon(self, name, x, y, size=32, cls="ico"):
        k = size / 24
        self.add(f'<g class="{cls}" transform="translate({x} {y}) scale({k:g})">{ICONS[name]}</g>')

    def node(self, nid, name, info, links, colour="infra"):
        self.add(f'<g class="node c-{colour}" data-id="{nid}" data-links="{" ".join(sorted(links))}" '
                 f'data-name="{escape(name)}" data-info="{escape(info)}" tabindex="0" role="button" '
                 f'aria-label="{escape(name)}: {escape(info)}">')

    def end(self):
        self.add("</g>")

    def edge(self, d, links, head_at=None, both=False, label=None, lx=0, ly=0):
        """d: path; head_at: list of (x, y, direction) arrow heads, direction in u/d/l/r."""
        self.add(f'<g class="edge-g" data-links="{" ".join(sorted(links))}">')
        self.add(f'<path class="edge" d="{d}"/>')
        for x, y, dirn in head_at or []:
            pts = {"d": f"{x - 8},{y - 12} {x + 8},{y - 12} {x},{y}", "u": f"{x - 8},{y + 12} {x + 8},{y + 12} {x},{y}",
                   "r": f"{x - 12},{y - 8} {x - 12},{y + 8} {x},{y}", "l": f"{x + 12},{y - 8} {x + 12},{y + 8} {x},{y}"}[dirn]
            self.add(f'<polygon class="edge-head" points="{pts}"/>')
        if label:
            self.text(lx, ly, label, 17, "t2")
        self.add("</g>")

    def render(self, sid):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" class="arch" id="{sid}" viewBox="0 0 {W} {H}" '
                f'role="group" aria-label="{escape(self.label)}">\n<style>{STYLE.strip()}</style>\n'
                + "\n".join(self.out) + "\n</svg>\n")


def top_band(svg, x, y, w, h, r=12, band=10):
    svg.add(f'<path class="band" d="M{x},{y + band} V{y + r} a{r},{r} 0 0 1 {r},{-r} H{x + w - r} '
            f'a{r},{r} 0 0 1 {r},{r} V{y + band} Z"/>')


def symmetric(links):
    """links: {id: set(ids)} → every link both ways."""
    out = {k: set(v) for k, v in links.items()}
    for k, vs in links.items():
        for v in vs:
            out.setdefault(v, set()).add(k)
    return out


# --------------------------------------------------------------------------- slide 1
def slide_one():
    svg = Svg("System architecture, part 1: the browser and the e-sign callback reach the nginx gateway, "
              "which routes to six agents; the drop folder and mailbox feed the document agent")
    ids = [a[0] for a in AGENTS]
    links = symmetric({
        "browser": {"gateway"},
        "esign": {"gateway", "ctr"},
        "gateway": set(ids),
        "inputs": {"doc"},
    })
    XS = [i * 243 for i in range(6)]
    CW, CY, CH = 223, 360, 280

    # edges first, so boxes paint over their ends
    svg.edge("M580,104 V172", {"browser", "gateway"}, [(580, 174, "d")],
             label="HTTPS + login token (JWT)", lx=594, ly=146)
    svg.edge("M1130,104 V172", {"esign", "gateway"}, [(1130, 174, "d")],
             label="signed callback", lx=1144, ly=146)
    for (aid, _, _, _, route, *_), x in zip(AGENTS, XS):
        cx = x + CW // 2
        lk = {"gateway", aid} | ({"esign"} if aid == "ctr" else set())
        svg.edge(f"M{cx},268 V{CY - 4}", lk, [(cx, CY - 2, "d")], label=route, lx=cx + 10, ly=322)
    svg.edge(f"M{CW // 2},700 V{CY + CH + 4}", {"inputs", "doc"}, [(CW // 2, CY + CH + 2, "u")],
             label="files, mail", lx=CW // 2 + 12, ly=678)

    svg.node("browser", "Web app", "the React app in the browser: one page per item, navigation by role "
             "(requester, approver, finance, admin), the admin Control Panel.", links["browser"])
    svg.add('<rect class="box" x="300" y="0" width="560" height="104" rx="14"/>')
    svg.icon("monitor", 326, 30, 44)
    svg.text(392, 46, "Web app", 26, "b")
    svg.text(392, 78, "React · requester, approver, finance, admin", 18, "t2")
    svg.end()

    svg.node("esign", "E-sign callback", "an outside e-signature provider reports a signature; the request is "
             "HMAC-signed and replay-protected, and reaches Contract & Risk through the gateway.", links["esign"])
    svg.add('<rect class="box" x="940" y="0" width="380" height="104" rx="14"/>')
    svg.icon("pen", 966, 30, 44)
    svg.text(1032, 46, "E-sign callback", 26, "b")
    svg.text(1032, 78, "signed webhook (HMAC)", 18, "t2")
    svg.end()

    svg.node("gateway", "nginx gateway", "the only public port (8080): serves the app, sends /api/<prefix> to the "
             "agent that owns it, rate-limits logins, adds security headers, caps uploads at 25 MB.", links["gateway"])
    svg.add('<rect class="gate" x="0" y="176" width="1440" height="92" rx="14"/>')
    svg.icon("shield", 28, 200, 44, "ico-l")
    svg.text(92, 216, "nginx gateway · :8080", 26, "b gate-t")
    svg.text(92, 248, "the only public port · serves the app · rate limits · security headers · 25 MB upload cap",
             18, "gate-t2")
    svg.end()

    for (aid, _, (n1, n2), port, _, (l1, l2), ai, icon, info), x in zip(AGENTS, XS):
        svg.node(aid, f"{n1} {n2}", info, links[aid], aid)
        svg.add(f'<rect class="box" x="{x}" y="{CY}" width="{CW}" height="{CH}" rx="14"/>')
        top_band(svg, x, CY, CW, CH, 14, 10)
        svg.add(f'<circle class="tint" cx="{x + 44}" cy="{CY + 52}" r="28"/>')
        svg.icon(icon, x + 28, CY + 36, 32)
        if ai:
            svg.add(f'<rect class="ai" x="{x + CW - 60}" y="{CY + 38}" width="42" height="28" rx="8"/>')
            svg.text(x + CW - 39, CY + 58, "AI", 17, "ai-t", "middle")
        svg.text(x + 20, CY + 124, n1, 24, "b")
        svg.text(x + 20, CY + 154, n2, 24, "b")
        svg.text(x + 20, CY + 186, port, 18, "b tc")
        svg.add(f'<line x1="{x + 20}" y1="{CY + 204}" x2="{x + CW - 20}" y2="{CY + 204}" stroke="var(--rule)"/>')
        svg.text(x + 20, CY + 234, l1, 18, "t2")
        svg.text(x + 20, CY + 262, l2, 18, "t2")
        svg.end()

    svg.node("inputs", "Drop folder and mailbox", "files copied into ./inbox/input are picked up every 3 seconds; "
             "the intake mailbox is read every 30 seconds. Both go straight to the document worker, not through "
             "the gateway.", links["inputs"], "doc")
    svg.add(f'<rect class="soft" x="0" y="700" width="{CW}" height="80" rx="14"/>')
    svg.icon("folder", 18, 722, 36)
    svg.text(66, 734, "Drop folder", 21, "b")
    svg.text(66, 762, "and mailbox", 18, "t2")
    svg.end()

    # key, bottom right
    svg.add('<g class="c-infra">')
    svg.add('<rect class="soft" x="300" y="700" width="1140" height="80" rx="14"/>')
    svg.add('<g class="c-appr"><rect class="ai" x="328" y="726" width="42" height="28" rx="8"/></g>')
    svg.text(349, 746, "AI", 17, "ai-t", "middle")
    svg.text(384, 746, "uses a trained model", 18, "t2")
    svg.add('<rect x="610" y="728" width="44" height="24" rx="6" fill="var(--rule)"/>'
            '<rect x="610" y="728" width="44" height="7" rx="3" fill="var(--ink2)"/>')
    svg.text(668, 746, "colour = one agent", 18, "t2")
    svg.text(870, 746, "+ worker = background jobs", 18, "t2")
    svg.text(1416, 746, "Next: how they talk ›", 18, "b", "end")
    svg.add("</g>")
    return svg.render("arch-1")


# --------------------------------------------------------------------------- slide 2
EVENTS = [  # topic, publisher, consumers
    ("document.ingested", "doc", {"doc"}),
    ("document.classified", "doc", {"appr", "ctr", "notif"}),
    ("approval.requested", "appr", {"ctr", "notif", "doc"}),
    ("approval.decided", "appr", {"ctr", "notif", "doc"}),
    ("contract.generated", "ctr", {"appr", "notif"}),
    ("contract.signed", "ctr", {"appr", "notif"}),
]
DATA = [  # id, title, two lines, users
    ("pg", "PostgreSQL 16 + pgvector", ("one shared database;", "each agent its own tables"), {a[0] for a in AGENTS}),
    ("minio", "MinIO", ("original documents", "(S3 storage)"), {"doc"}),
    ("redis", "Redis", ("stock reservation locks,", "repeat-safe requests"), {"appr"}),
    ("models", "Trained models", ("LayoutLMv3 · Legal-BERT", "scikit-learn"), {"doc", "appr", "ctr"}),
]
EXTERNAL = [  # id, name, what for, users
    ("clamav", "ClamAV", "virus scan of every upload", {"doc"}),
    ("mail", "Mailpit / SMTP", "every email sent", {"notif", "auth", "doc"}),
    ("ollama", "Ollama", "local LLM for the assistant", {"chat"}),
    ("fx", "Frankfurter", "exchange rates to INR", {"doc"}),
    ("ifsc", "IFSC and GSTIN lookups", "bank and tax ids", {"doc"}),
    ("hibp", "HaveIBeenPwned", "breached-password check", {"auth"}),
    ("sanctions", "OpenSanctions", "sanctions list", {"ctr"}),
]
TEMPORAL = [
    ("sla", "Approval SLAs", ("reminders at 50% and", "80%, then escalation"), {"appr"}),
    ("renew", "Contract renewals", ("notice before a", "contract expires"), {"ctr"}),
]


def slide_two():
    svg = Svg("System architecture, part 2: the six agents talk through Kafka events and Temporal workflows, "
              "keep data in PostgreSQL, MinIO and Redis, and call outside services over HTTP")
    raw = {"kafka": {"doc", "appr", "ctr", "notif", "auth"}, "temporal": {"appr", "ctr"}}
    for t, pub, subs in EVENTS:
        raw["ev-" + t] = {pub} | subs
    for i, *_rest, users in DATA:
        raw[i] = set(users)
    for i, *_rest, users in EXTERNAL:
        raw[i] = set(users)
    for i, *_rest, users in TEMPORAL:
        raw[i] = set(users)
    links = symmetric(raw)

    cols = {  # x, width
        "kafka": (0, 400), "temporal": (426, 260), "data": (712, 360), "ext": (1098, 342),
    }
    col_members = {
        "kafka": {"kafka"} | {"ev-" + e[0] for e in EVENTS},
        "temporal": {"temporal", "sla", "renew"},
        "data": {d[0] for d in DATA},
        "ext": {e[0] for e in EXTERNAL},
    }
    labels = {"kafka": "publish · consume", "temporal": "start · signal", "data": "SQL · files", "ext": "HTTP"}
    # each connector leaves the band between two agents, so it reads as "the agents", not one of them
    gap_x = {"kafka": 244, "temporal": 481, "data": 955, "ext": 1192}
    for c in cols:
        members = col_members[c]
        users = set().union(*(links.get(m, set()) for m in members)) & set(AGENT)
        cx = gap_x[c]
        heads = [(cx, 166, "d")] + ([(cx, 94, "u")] if c == "kafka" else [])
        svg.edge(f"M{cx},{96 if c == 'kafka' else 92} V164", members | users, heads,
                 label=labels[c], lx=cx + 14, ly=136)

    # agents band
    svg.add('<rect class="soft c-infra" x="0" y="0" width="1440" height="92" rx="14"/>')
    for i, (aid, short, _, port, *_rest) in enumerate(AGENTS):
        x = 14 + i * 237
        info = AGENT[aid][8]
        svg.node(aid, f"{AGENT[aid][2][0]} {AGENT[aid][2][1]}".strip(), info, links.get(aid, set()), aid)
        svg.add(f'<rect class="box" x="{x}" y="14" width="223" height="64" rx="10"/>')
        svg.add(f'<rect class="band" x="{x}" y="14" width="8" height="64" rx="3"/>')
        svg.icon(AGENT[aid][7], x + 22, 30, 32)
        svg.text(x + 66, 44, short, 20, "b")
        svg.text(x + 66, 68, port.split(" ")[0], 16, "t3")
        svg.end()

    def col_head(x, w, icon, title, sub, nid=None, info="", ext=False):
        if nid:
            svg.node(nid, title, info, links[nid])
        else:
            svg.add('<g class="c-infra">')
        svg.add(f'<rect class="{"ext" if ext else "soft"}" x="{x}" y="170" width="{w}" height="490" rx="14"/>')
        svg.icon(icon, x + 20, 190, 36)
        svg.text(x + 68, 208, title, 24, "b")
        svg.text(x + 68, 236, sub, 17, "t3")
        svg.end()

    # Kafka
    x, w = cols["kafka"]
    col_head(x, w, "zap", "Kafka events", "Redpanda · 23 topics", "kafka",
             "carries every hand-off between agents as an event. 23 topics; each agent has its own login and may "
             "use only its own topics. An event is saved in the same transaction as the change (outbox), so a "
             "restart loses nothing.")
    y = 262
    for i, (t, pub, subs) in enumerate(EVENTS):
        names = ", ".join(AGENT[s][1] for s in sorted(subs, key=list(AGENT).index))
        svg.node("ev-" + t, t, f"published by {AGENT[pub][1]}; read by {names}.", links["ev-" + t], pub)
        svg.add(f'<rect class="box" x="{x + 24}" y="{y}" width="{w - 48}" height="42" rx="21"/>')
        svg.add(f'<circle class="band" cx="{x + 46}" cy="{y + 21}" r="7"/>')
        svg.text(x + 64, y + 28, t, 18, "mono")
        svg.end()
        if i < len(EVENTS) - 1:
            svg.add(f'<path class="edge" d="M{x + 46},{y + 44} V{y + 56}" style="stroke-width:1.6"/>')
        y += 56
    svg.text(x + 24, 636, "saved with the change (outbox)", 17, "t3")

    # Temporal
    x, w = cols["temporal"]
    col_head(x, w, "clock", "Temporal", "durable workflows", "temporal",
             "runs the long waits that must survive restarts: approval deadlines with reminders and escalation, and "
             "contract renewal notices. Workers in Approval and Contract poll it.")
    y = 262
    for tid, title, (l1, l2), users in TEMPORAL:
        owner = sorted(users)[0]
        svg.node(tid, title, f"{l1} {l2} (run by {AGENT[owner][1]}).", links[tid], owner)
        svg.add(f'<rect class="box" x="{x + 20}" y="{y}" width="{w - 40}" height="112" rx="12"/>')
        svg.add(f'<rect class="band" x="{x + 20}" y="{y + 16}" width="6" height="80" rx="3"/>')
        svg.text(x + 40, y + 38, title, 20, "b")
        svg.text(x + 40, y + 68, l1, 17, "t2")
        svg.text(x + 40, y + 94, l2, 17, "t2")
        svg.end()
        y += 128

    # Data
    x, w = cols["data"]
    col_head(x, w, "db", "Data", "inside the Docker network")
    y = 262
    for did, title, (l1, l2), users in DATA:
        who = "every agent" if len(users) == 6 else ", ".join(AGENT[u][1] for u in sorted(users, key=list(AGENT).index))
        svg.node(did, title, f"{l1} {l2}. Used by {who}.", links[did])
        svg.add(f'<rect class="box" x="{x + 20}" y="{y}" width="{w - 40}" height="88" rx="12"/>')
        svg.text(x + 40, y + 32, title, 20, "b")
        svg.text(x + 40, y + 58, l1, 17, "t2")
        svg.text(x + 40, y + 80, l2, 17, "t2")
        svg.end()
        y += 98

    # External
    x, w = cols["ext"]
    col_head(x, w, "globe", "Outside services", "called over HTTP", ext=True)
    y = 262
    for eid, name, what, users in EXTERNAL:
        who = ", ".join(AGENT[u][1] for u in sorted(users, key=list(AGENT).index))
        svg.node(eid, name, f"{what}. Used by {who}.", links[eid])
        svg.add(f'<rect x="{x + 12}" y="{y - 4}" width="{w - 24}" height="54" rx="8" fill="transparent"/>')
        svg.text(x + 24, y + 18, name, 19, "b")
        svg.text(x + 24, y + 42, what, 16, "t2")
        svg.end()
        y += 56

    # observability strip
    svg.add('<g class="c-infra">')
    svg.add('<rect class="soft" x="0" y="700" width="1440" height="80" rx="14"/>')
    svg.icon("pulse", 24, 722, 36)
    svg.text(76, 748, "Watching it run", 21, "b")
    svg.text(260, 748, "Prometheus metrics  ·  Loki logs by correlation id  ·  Grafana dashboards  ·  Temporal UI",
             18, "t2")
    svg.text(1416, 748, "Click any box", 18, "t3", "end")
    svg.add("</g>")
    return svg.render("arch-2")


def put_in_deck(svgs):
    """Refresh the copies between <!-- arch:N --> markers in the Slides tab."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import docs_dashboard as dash
    page = dash.read_pages()["slides"]
    for n, s in enumerate(svgs, 1):
        pat = re.compile(rf"(<!-- arch:{n} -->).*?(<!-- /arch:{n} -->)", re.S)
        if not pat.search(page):
            print(f"slides tab has no <!-- arch:{n} --> marker; skipped")
            return
        page = pat.sub(lambda m: m.group(1) + "\n" + s + m.group(2), page)
    dash.replace_page("slides", page)
    print("updated the Slides tab")


if __name__ == "__main__":
    svgs = [slide_one(), slide_two()]
    for n, s in enumerate(svgs, 1):
        path = os.path.join(HERE, f"architecture-{n}.svg")
        with open(path, "w") as f:
            f.write(s)
        print("written", os.path.relpath(path, ROOT))
    put_in_deck(svgs)
