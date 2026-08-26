// Vanilla JS, no build step — every fetch goes through the gateway at
// /api/* (same origin as this page, served by the nginx container), so
// there's no CORS to configure and no separate frontend port to keep in
// sync with the gateway's routing table.
const API_BASE = "/api";
const AUTH_KEY = "itpip_auth";

const ROLE_NEXT_STEP = {
  requester: "<strong>Document Review</strong> (upload something) or <strong>Approver Inbox</strong> (create a request).",
  approver: "<strong>Approver Inbox</strong> — approve/reject pending requests.",
  finance: "<strong>Approver Inbox</strong> — approve higher-spend-tier requests.",
  admin: "<strong>Contracts &amp; Vendor Risk</strong> — generate/sign contracts, score or offboard vendors.",
};

function getAuth() {
  try { return JSON.parse(localStorage.getItem(AUTH_KEY) || "null"); } catch { return null; }
}
function setAuth(auth) { localStorage.setItem(AUTH_KEY, JSON.stringify(auth)); }
function clearAuth() { localStorage.removeItem(AUTH_KEY); }

async function api(path, opts = {}) {
  const auth = getAuth();
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (auth && auth.access_token) headers["Authorization"] = "Bearer " + auth.access_token;

  const res = await fetch(API_BASE + path, Object.assign({}, opts, { headers }));
  if (res.status === 401) {
    clearAuth();
    showLogin("Session expired — please sign in again.");
    throw new Error("unauthorized");
  }
  let body = null;
  try { body = await res.json(); } catch { /* no body */ }
  if (!res.ok) {
    const msg = body && body.error ? body.error.message : (body && body.detail) || res.statusText;
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return body;
}

async function apiUpload(path, formData) {
  const auth = getAuth();
  const headers = {};
  if (auth && auth.access_token) headers["Authorization"] = "Bearer " + auth.access_token;
  const res = await fetch(API_BASE + path, { method: "POST", headers, body: formData });
  let body = null;
  try { body = await res.json(); } catch {}
  if (!res.ok) {
    const msg = body && body.error ? body.error.message : (body && body.detail) || res.statusText;
    throw new Error(msg || `HTTP ${res.status}`);
  }
  return body;
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) if (c) node.appendChild(c);
  return node;
}

function badge(text, cls) {
  return el("span", { class: `badge ${cls || (text || "").toLowerCase()}`, text: text || "—" });
}

function errorBanner(message) {
  return el("div", { class: "error-banner", text: `⚠ ${message}` });
}
function okBanner(message) {
  return el("div", { class: "ok-banner", text: `✓ ${message}` });
}

// ---------- Login ----------

function showLogin(message) {
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("app-screen").style.display = "none";
  const errBox = document.getElementById("login-error");
  errBox.innerHTML = "";
  if (message) errBox.appendChild(errorBanner(message));
}

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  document.getElementById("app-screen").style.display = "block";
  const auth = getAuth();
  const whoLabel = document.getElementById("who-label");
  whoLabel.innerHTML = "";
  whoLabel.appendChild(document.createTextNode(auth.email + " "));
  whoLabel.appendChild(badge(auth.role, "role-badge"));
  renderActiveTab();
}

async function doLogin() {
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;
  const btn = document.getElementById("login-btn");
  btn.disabled = true;
  try {
    const resp = await fetch(API_BASE + "/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const body = await resp.json();
    if (!resp.ok) throw new Error((body.error && body.error.message) || "login failed");
    setAuth({
      access_token: body.data.access_token,
      refresh_token: body.data.refresh_token,
      email, role: null,
    });
    const me = await api("/auth/me");
    const auth = getAuth();
    auth.role = me.data.role;
    auth.email = me.data.email;
    setAuth(auth);
    showApp();
  } catch (e) {
    showLogin(e.message);
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("login-btn").addEventListener("click", doLogin);
document.getElementById("login-password").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
document.getElementById("logout-btn").addEventListener("click", () => { clearAuth(); showLogin(); });
document.querySelectorAll(".role-quickpick .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.getElementById("login-email").value = chip.dataset.email;
    document.getElementById("login-password").value = "DemoPass123!";
    document.querySelectorAll(".role-quickpick .chip").forEach((c) => c.classList.toggle("active", c === chip));
  });
});

// ---------- Tabs ----------

const TAB_RENDERERS = { about: renderAbout, overview: renderOverview, contracts: renderContracts, approvals: renderApprovals, documents: renderDocuments };
let activeTab = "about";

document.getElementById("tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  activeTab = btn.dataset.tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === btn));
  document.querySelectorAll("main > section").forEach((s) => (s.style.display = "none"));
  document.getElementById(`tab-${activeTab}`).style.display = "block";
  renderActiveTab();
});

function renderActiveTab() {
  TAB_RENDERERS[activeTab]();
}

function goToTab(tab) {
  document.querySelector(`#tabs button[data-tab="${tab}"]`).click();
}

// ---------- About / How It Works ----------

function renderAbout() {
  const root = document.getElementById("tab-about");
  root.innerHTML = "";
  const auth = getAuth();

  // --- Why this project ---
  const why = el("div", { class: "panel" });
  why.appendChild(el("h2", { text: "Why this project" }));
  why.appendChild(el("p", { class: "desc", html:
    "IT procurement at most organizations still runs through email threads, spreadsheets, and " +
    "whoever remembers to chase an approval. A vendor invoice arrives as a PDF and someone retypes " +
    "it. A purchase sits waiting for the right manager to notice it. A contract auto-renews because " +
    "nobody tracked the notice period. A vendor's bank details change and nobody double-checks it's " +
    "really the vendor asking. None of this is a technology problem in the sense of missing tools — " +
    "it's a problem of nothing in the chain actually talking to anything else." }));
  why.appendChild(el("p", { class: "desc", html:
    "This platform wires those steps into <strong>one event-driven pipeline</strong>: a document " +
    "upload triggers extraction, extraction triggers vendor matching, an approval triggers a contract, " +
    "a signed contract triggers a risk score and a renewal timer, and every step notifies the right " +
    "person automatically. The goal isn't to replace judgment — approvals, risk decisions, and " +
    "payment-detail changes still need a human — it's to remove the manual busywork and the silent " +
    "gaps around those decisions." }));
  root.appendChild(why);

  // --- How it works ---
  const how = el("div", { class: "panel" });
  how.appendChild(el("h2", { text: "How it works" }));
  how.appendChild(el("p", { class: "desc", text:
    "Four independent services, each owning one part of the lifecycle, talking to each other only " +
    "through Kafka events and a shared Postgres schema — never by calling each other's code directly. " +
    "That's what lets them fail, scale, and get rebuilt independently." }));
  how.appendChild(buildArchitectureDiagram());
  how.appendChild(el("p", { class: "small muted", style: "margin-top:14px", html:
    "Every request into any service goes through the same gateway (nginx, this page's own origin) and " +
    "the same JWT check. Every service exposes <code>/health</code> and <code>/metrics</code> " +
    "(scraped by Prometheus, visualized in Grafana at :3000)." }));
  root.appendChild(how);

  // --- Try it yourself ---
  const walkthrough = el("div", { class: "panel" });
  walkthrough.appendChild(el("h2", { text: "Try it yourself — the full loop, start to finish" }));
  walkthrough.appendChild(el("p", { class: "desc", text:
    "This is exactly the path the automated end-to-end test scripts. Switch roles with the inbox in " +
    "the top-right (sign out, sign back in) as you go — each step below names which role does it." }));
  const steps = [
    ["requester", "Document Review", "Upload a PO/invoice/quote (or use the sample files in data/synthetic-invoices/). It's scanned for malware, stored, then classified and field-extracted in the background — refresh the review queue a few seconds later."],
    ["requester", "Approver Inbox → Create a purchase request", "Or skip straight to this if you don't want to wait on document extraction — it's the same downstream flow either way."],
    ["approver / finance", "Approver Inbox", "Load the inbox for the request's approver role (e.g. dept_manager) and approve it. This signals a running workflow — status settles within a second or two, it's not instant."],
    ["admin / approver / finance", "Contracts & Vendor Risk", "Generate a contract from the now-approved request, then send it for signature."],
    ["— (automated)", "—", "In a real deployment the e-sign provider calls back when the document is actually signed. This demo doesn't have a live e-sign provider wired in, so there's no button for this step — the contract stays in \"pending signature\" here, and the automated e2e test (make e2e) simulates the callback directly against the API to prove the rest of the chain (signing → risk scoring → notification) works."],
    ["anyone", "Contracts & Vendor Risk → Vendor risk", "Look up or recompute the vendor's risk score — this is what a signed contract triggers automatically."],
    ["—", "Mailpit (localhost:8025)", "Every step above sends an email — check Mailpit's inbox to see them land."],
  ];
  const table = el("table");
  table.appendChild(el("tr", {}, [el("th", { text: "#" }), el("th", { text: "Role" }), el("th", { text: "Tab" }), el("th", { text: "What happens" })]));
  steps.forEach((s, i) => {
    table.appendChild(el("tr", {}, [
      el("td", { text: String(i + 1) }),
      el("td", {}, badge(s[0], "role-badge")),
      el("td", { text: s[1] }),
      el("td", { class: "small", text: s[2] }),
    ]));
  });
  walkthrough.appendChild(table);
  root.appendChild(walkthrough);

  // --- Project layout ---
  const layout = el("div", { class: "panel" });
  layout.appendChild(el("h2", { text: "Project layout" }));
  const svcTable = el("table");
  svcTable.appendChild(el("tr", {}, [el("th", { text: "Service" }), el("th", { text: "Owns" }), el("th", { text: "Port" }), el("th", { text: "Key tech" })]));
  const services = [
    ["document-vendor-agent", "Upload, malware scan, OCR/classify, vendor match & dedup, payment-detail governance", "8001", "MinIO, ClamAV, pdfplumber/Tesseract, rapidfuzz"],
    ["approval-inventory-agent", "Spend-tier approval chains, SLA escalation, inventory reservation, license utilisation", "8002", "Temporal, Redis locks"],
    ["contract-risk-agent", "Contract generation, clause extraction, e-sign webhook, vendor risk scoring, drift monitoring", "8003", "Jinja2, scikit-learn, MLflow, Temporal"],
    ["notification-agent", "Email rendering + delivery, urgent vs. digest batching, audit log of sends", "8004", "Jinja2, SMTP → Mailpit"],
    ["auth-service", "Login, JWT issuance/refresh, demo user seeding", "8005", "bcrypt, PyJWT"],
  ];
  services.forEach((s) => svcTable.appendChild(el("tr", {}, s.map((v) => el("td", { text: v })))));
  layout.appendChild(svcTable);
  layout.appendChild(el("p", { class: "small muted", style: "margin-top:12px", html:
    "Every service shares one Postgres database and one Kafka bus (Redpanda), but never queries another " +
    "service's tables directly or imports its code — the only contracts between them are the documented " +
    "Kafka event shapes and the REST endpoints through the gateway. This page is served as static files " +
    "by the same nginx container that proxies <code>/api/*</code> to each service — no separate frontend " +
    "server, no CORS." }));
  root.appendChild(layout);

  // --- Roles ---
  const roles = el("div", { class: "panel" });
  roles.appendChild(el("h2", { text: "Roles" }));
  const roleTable = el("table");
  roleTable.appendChild(el("tr", {}, [el("th", { text: "Role" }), el("th", { text: "Can do" })]));
  [
    ["requester", "Upload documents, create purchase requests"],
    ["approver", "Approve/reject requests, recompute vendor risk"],
    ["finance", "Same as approver, plus higher-spend-tier approvals"],
    ["admin", "Everything above, plus generate/sign contracts, offboard vendors"],
  ].forEach(([r, d]) => roleTable.appendChild(el("tr", {}, [el("td", {}, badge(r, "role-badge")), el("td", { text: d })])));
  roles.appendChild(roleTable);
  if (auth) {
    roles.appendChild(el("p", { class: "small muted", style: "margin-top:10px", html: `You're signed in as <strong>${auth.email}</strong> (<code>${auth.role}</code>) — actions outside your role return a clear "forbidden" message rather than failing silently.` }));
  }
  root.appendChild(roles);
}

function buildArchitectureDiagram() {
  const wrap = el("div", { class: "diagram" });

  const col = (title, items) => {
    const c = el("div", { class: "diagram-col" });
    c.appendChild(el("div", { class: "diagram-col-title", text: title }));
    items.forEach((it) => c.appendChild(el("div", { class: "diagram-node", text: it })));
    return c;
  };

  wrap.appendChild(col("Frontend", ["This page (nginx)"]));
  wrap.appendChild(el("div", { class: "diagram-arrow", text: "→" }));
  wrap.appendChild(col("Gateway", ["nginx :8080", "/api/* routing", "JWT check"]));
  wrap.appendChild(el("div", { class: "diagram-arrow", text: "→" }));
  wrap.appendChild(col("Services", [
    "document-vendor-agent",
    "approval-inventory-agent",
    "contract-risk-agent",
    "notification-agent",
    "auth-service",
  ]));
  wrap.appendChild(el("div", { class: "diagram-arrow", text: "⇄" }));
  wrap.appendChild(col("Shared infra", [
    "Postgres (one schema)",
    "Kafka / Redpanda",
    "Redis, MinIO",
    "Temporal workflows",
  ]));
  return wrap;
}

// ---------- Overview ----------

async function renderOverview() {
  const root = document.getElementById("tab-overview");
  root.innerHTML = "";
  const auth = getAuth();

  const banner = el("div", { class: "step-banner" });
  banner.appendChild(el("div", { class: "icon", text: "👋" }));
  const bannerText = el("div");
  bannerText.appendChild(el("div", { html: `First time here? The <button class="link-btn" id="ov-goto-about">How It Works</button> tab walks through the whole demo loop step by step.` }));
  const nextStep = ROLE_NEXT_STEP[auth?.role];
  if (nextStep) {
    bannerText.appendChild(el("div", { class: "small muted", style: "margin-top:4px", html: `As <strong>${auth.role}</strong>, you'll mostly use: ${nextStep}` }));
  }
  banner.appendChild(bannerText);
  root.appendChild(banner);
  root.querySelector("#ov-goto-about").addEventListener("click", () => goToTab("about"));

  const panel = el("div", { class: "panel" });
  panel.appendChild(el("h2", { text: "Platform status" }));
  panel.appendChild(el("p", { class: "desc", text: "Live counts pulled through the gateway from each service." }));
  const grid = el("div", { class: "stat-grid" });
  panel.appendChild(grid);
  root.appendChild(panel);

  const stat = (n, l) => el("div", { class: "stat-card" }, [el("div", { class: "n", text: n }), el("div", { class: "l", text: l })]);

  try {
    const inv = await api("/inventory/");
    grid.appendChild(stat(String(inv.data.hardware.length), "Hardware SKUs"));
    grid.appendChild(stat(String(inv.data.licenses.length), "Licenses tracked"));
  } catch (e) {
    grid.appendChild(stat("—", "Hardware SKUs"));
    grid.appendChild(stat("—", "Licenses tracked"));
  }
  try {
    const renewals = await api("/contracts/renewals-due?within_days=60");
    grid.appendChild(stat(String(renewals.data.length), "Contracts renewing (60d)"));
  } catch (e) {
    grid.appendChild(stat("—", "Contracts renewing (60d)"));
  }
  try {
    const docs = await api("/documents/review-queue");
    grid.appendChild(stat(String(docs.data.length), "Documents needing review"));
  } catch (e) {
    grid.appendChild(stat("—", "Documents needing review"));
  }

  const help = el("div", { class: "panel" });
  help.appendChild(el("h2", { text: "Where things live" }));
  help.appendChild(el("p", { class: "desc", html:
    "<strong>Contracts &amp; Vendor Risk</strong> — generate contracts, route for e-signature, inspect renewal dates, score/offboard vendors.<br>" +
    "<strong>Approver Inbox</strong> — pending purchase requests routed to an approver role, approve/reject.<br>" +
    "<strong>Document Review</strong> — upload a PO/invoice/quote, correct low-confidence extractions." }));
  root.appendChild(help);
}

// ---------- Contracts & Vendor Risk ----------

async function renderContracts() {
  const root = document.getElementById("tab-contracts");
  root.innerHTML = "";

  root.appendChild(el("div", { class: "help-text", html:
    "Don't have a purchase request ID handy? Run <code>./scripts/seed-demo-data.sh</code> for a ready-made " +
    "approved request + vendor, or approve one yourself in the <strong>Approver Inbox</strong> tab first." }));

  // --- Generate contract ---
  const genPanel = el("div", { class: "panel" });
  genPanel.appendChild(el("h2", { text: "Generate a contract" }));
  genPanel.appendChild(el("p", { class: "desc", text: "From an approved purchase request. Requires approver/finance/admin." }));
  const genMsg = el("div");
  const prInput = el("input", { placeholder: "purchase_request_id (uuid)" });
  const templateSelect = el("select", {}, [
    el("option", { value: "hardware_purchase", text: "hardware_purchase" }),
    el("option", { value: "saas_subscription", text: "saas_subscription" }),
    el("option", { value: "professional_services", text: "professional_services" }),
  ]);
  const genBtn = el("button", { text: "Generate" });
  genPanel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field" }, [el("label", { text: "Purchase request ID" }), prInput]),
    el("div", { class: "field" }, [el("label", { text: "Template" }), templateSelect]),
    genBtn,
  ]));
  genPanel.appendChild(genMsg);
  const contractOut = el("div");
  genPanel.appendChild(contractOut);
  root.appendChild(genPanel);

  function renderContract(c) {
    contractOut.innerHTML = "";
    const table = el("table");
    const rows = [
      ["ID", c.id], ["Status", null], ["Vendor", c.vendor_id], ["Template", c.template_used],
      ["Renewal type", c.renewal_type], ["Notice period (days)", c.notice_period_days],
      ["Contract end date", c.contract_end_date], ["Signed by", c.signed_by || "—"],
      ["Reconciliation", c.reconciliation_status || "—"],
    ];
    for (const [k, v] of rows) {
      const tr = el("tr");
      tr.appendChild(el("td", { text: k }));
      if (k === "Status") tr.appendChild(el("td", {}, badge(c.status)));
      else tr.appendChild(el("td", { text: v == null ? "—" : String(v) }));
      table.appendChild(tr);
    }
    contractOut.appendChild(table);
    if (c.status === "draft") {
      const signBtn = el("button", { text: "Send for signature" });
      signBtn.addEventListener("click", async () => {
        try {
          const r = await api(`/contracts/${c.id}/send-for-signature`, { method: "POST", body: "{}" });
          contractOut.prepend(okBanner("Sent for signature."));
          renderContract(r.data);
        } catch (e) { contractOut.prepend(errorBanner(e.message)); }
      });
      contractOut.appendChild(el("div", { style: "margin-top:10px" }, signBtn));
    }
    if (c.contract_text) {
      contractOut.appendChild(el("pre", { class: "contract-text", text: c.contract_text }));
    }
  }

  genBtn.addEventListener("click", async () => {
    genMsg.innerHTML = "";
    if (!prInput.value.trim()) { genMsg.appendChild(errorBanner("Enter a purchase request ID.")); return; }
    try {
      const r = await api("/contracts/generate", {
        method: "POST",
        body: JSON.stringify({ purchase_request_id: prInput.value.trim(), template_name: templateSelect.value }),
      });
      genMsg.appendChild(okBanner("Contract generated."));
      renderContract(r.data);
    } catch (e) { genMsg.appendChild(errorBanner(e.message)); }
  });

  // --- Look up a contract ---
  const lookupPanel = el("div", { class: "panel" });
  lookupPanel.appendChild(el("h2", { text: "Look up a contract" }));
  const lookupMsg = el("div");
  const lookupInput = el("input", { placeholder: "contract_id (uuid)" });
  const lookupBtn = el("button", { text: "Fetch" });
  lookupPanel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field" }, [el("label", { text: "Contract ID" }), lookupInput]),
    lookupBtn,
  ]));
  lookupPanel.appendChild(lookupMsg);
  const lookupOut = el("div");
  lookupPanel.appendChild(lookupOut);
  root.appendChild(lookupPanel);

  lookupBtn.addEventListener("click", async () => {
    lookupMsg.innerHTML = ""; lookupOut.innerHTML = "";
    try {
      const r = await api(`/contracts/${lookupInput.value.trim()}`);
      const prevOut = contractOut; // reuse renderContract by temporarily swapping target
      lookupOut.innerHTML = "";
      const table = document.createElement("div");
      lookupOut.appendChild(table);
      const tmp = contractOut;
      // simplest: just call the same renderer against lookupOut
      renderInto(lookupOut, r.data);
    } catch (e) { lookupMsg.appendChild(errorBanner(e.message)); }
  });

  function renderInto(target, c) {
    target.innerHTML = "";
    const table = el("table");
    const rows = [
      ["ID", c.id], ["Vendor", c.vendor_id], ["Template", c.template_used],
      ["Renewal type", c.renewal_type], ["Notice period (days)", c.notice_period_days],
      ["Contract end date", c.contract_end_date], ["Signed by", c.signed_by || "—"],
    ];
    const trStatus = el("tr", {}, [el("td", { text: "Status" }), el("td", {}, badge(c.status))]);
    table.appendChild(trStatus);
    for (const [k, v] of rows) {
      table.appendChild(el("tr", {}, [el("td", { text: k }), el("td", { text: v == null ? "—" : String(v) })]));
    }
    target.appendChild(table);
    if (c.contract_text) target.appendChild(el("pre", { class: "contract-text", text: c.contract_text }));
  }

  // --- Renewals due ---
  const renewalPanel = el("div", { class: "panel" });
  renewalPanel.appendChild(el("h2", { text: "Renewals due" }));
  const withinInput = el("input", { type: "number", value: "60", style: "max-width:100px" });
  const renewalBtn = el("button", { text: "Refresh" });
  renewalPanel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field", style: "flex:0" }, [el("label", { text: "Within days" }), withinInput]),
    renewalBtn,
  ]));
  const renewalOut = el("div", { class: "empty", text: "Click refresh." });
  renewalPanel.appendChild(renewalOut);
  root.appendChild(renewalPanel);

  renewalBtn.addEventListener("click", async () => {
    renewalOut.innerHTML = "Loading…";
    try {
      const r = await api(`/contracts/renewals-due?within_days=${withinInput.value}`);
      if (!r.data.length) { renewalOut.innerHTML = ""; renewalOut.appendChild(el("div", { class: "empty", text: "Nothing renewing in this window." })); return; }
      const table = el("table");
      table.appendChild(el("tr", {}, [el("th", { text: "Contract" }), el("th", { text: "Status" }), el("th", { text: "End date" }), el("th", { text: "Renewal" })]));
      r.data.forEach((c) => table.appendChild(el("tr", {}, [
        el("td", { text: c.id }), el("td", {}, badge(c.status)), el("td", { text: c.contract_end_date }), el("td", { text: c.renewal_type || "—" }),
      ])));
      renewalOut.innerHTML = ""; renewalOut.appendChild(table);
    } catch (e) { renewalOut.innerHTML = ""; renewalOut.appendChild(errorBanner(e.message)); }
  });

  // --- Vendor risk ---
  const riskPanel = el("div", { class: "panel" });
  riskPanel.appendChild(el("h2", { text: "Vendor risk" }));
  riskPanel.appendChild(el("p", { class: "desc", text: "Look up, recompute, log an outcome, or offboard a vendor." }));
  const riskMsg = el("div");
  const vendorInput = el("input", { placeholder: "vendor_id (uuid)" });
  const riskGetBtn = el("button", { class: "secondary", text: "Get risk" });
  const riskRecomputeBtn = el("button", { text: "Recompute" });
  const offboardBtn = el("button", { class: "danger", text: "Offboard vendor" });
  riskPanel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field" }, [el("label", { text: "Vendor ID" }), vendorInput]),
    riskGetBtn, riskRecomputeBtn, offboardBtn,
  ]));
  riskPanel.appendChild(riskMsg);
  const riskOut = el("div");
  riskPanel.appendChild(riskOut);
  root.appendChild(riskPanel);

  function renderRisk(d) {
    riskOut.innerHTML = "";
    riskOut.appendChild(el("div", { class: "row" }, [
      el("div", {}, [el("div", { class: "small muted", text: "Band" }), badge(d.risk_band)]),
      el("div", {}, [el("div", { class: "small muted", text: "Score" }), el("div", { text: (d.risk_score ?? 0).toFixed(3) })]),
      el("div", {}, [el("div", { class: "small muted", text: "Model" }), el("div", { text: d.model_version || "—" })]),
    ]));
    if (d.top_factors && d.top_factors.length) {
      const maxC = Math.max(...d.top_factors.map((f) => f.contribution));
      d.top_factors.forEach((f) => {
        riskOut.appendChild(el("div", { class: "bar-row" }, [
          el("div", { class: "label", text: f.feature }),
          el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${maxC ? (f.contribution / maxC) * 100 : 0}%` })),
          el("div", { class: "val", text: f.contribution.toFixed(3) }),
        ]));
      });
    }
  }

  riskGetBtn.addEventListener("click", async () => {
    riskMsg.innerHTML = ""; riskOut.innerHTML = "";
    try { renderRisk((await api(`/vendors/${vendorInput.value.trim()}/risk`)).data); }
    catch (e) { riskMsg.appendChild(errorBanner(e.message)); }
  });
  riskRecomputeBtn.addEventListener("click", async () => {
    riskMsg.innerHTML = "";
    try {
      const r = await api(`/vendors/${vendorInput.value.trim()}/risk/recompute`, { method: "POST" });
      riskMsg.appendChild(okBanner("Recomputed."));
      renderRisk(r.data);
    } catch (e) { riskMsg.appendChild(errorBanner(e.message)); }
  });
  offboardBtn.addEventListener("click", async () => {
    riskMsg.innerHTML = "";
    if (!confirm("Offboard this vendor? This revokes portal access and flags active contracts for reconciliation.")) return;
    const auth = getAuth();
    try {
      const r = await api(`/vendors/${vendorInput.value.trim()}/offboard`, {
        method: "POST",
        body: JSON.stringify({ offboarded_by: auth.email, reason: "offboarded via demo UI" }),
      });
      riskMsg.appendChild(okBanner(`Offboarded. Contracts flagged: ${r.data.contracts_flagged.length}`));
    } catch (e) { riskMsg.appendChild(errorBanner(e.message)); }
  });
}

// ---------- Approver Inbox ----------

async function renderApprovals() {
  const root = document.getElementById("tab-approvals");
  root.innerHTML = "";

  const panel = el("div", { class: "panel" });
  panel.appendChild(el("h2", { text: "Approver inbox" }));
  panel.appendChild(el("div", { class: "help-text", html:
    "Requests route to an <strong>approver role</strong> (from the spend-tier chain in config.yaml), " +
    "not an individual person — <code>dept_manager</code> handles the $500–$5,000 tier, " +
    "<code>finance_head</code> is added for anything above that. Pick the role below, then load its inbox." }));
  const approverInput = el("select", {}, [
    el("option", { value: "dept_manager", text: "dept_manager (manager tier)" }),
    el("option", { value: "finance_head", text: "finance_head (manager+finance tier)" }),
  ]);
  const refreshBtn = el("button", { text: "Load inbox" });
  panel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field", style: "flex:0;min-width:220px" }, [el("label", { text: "Approver role" }), approverInput]),
    refreshBtn,
  ]));
  const msg = el("div");
  panel.appendChild(msg);
  const out = el("div", { class: "empty", text: "Click load inbox." });
  panel.appendChild(out);
  root.appendChild(panel);

  async function load() {
    msg.innerHTML = ""; out.innerHTML = "Loading…";
    try {
      const r = await api(`/inbox/${encodeURIComponent(approverInput.value.trim())}`);
      if (!r.data.length) { out.innerHTML = ""; out.appendChild(el("div", { class: "empty", text: "Nothing pending for this approver." })); return; }
      out.innerHTML = "";
      const table = el("table");
      table.appendChild(el("tr", {}, [
        el("th", { text: "Request" }), el("th", { text: "Type" }), el("th", { text: "Dept" }),
        el("th", { text: "Amount" }), el("th", { text: "Tier" }), el("th", { text: "SLA" }), el("th", { text: "Action" }),
      ]));
      r.data.forEach((req) => {
        const decideBtn = (decision, cls) => {
          const label = decision === "approve" ? "Approve" : "Reject";
          const b = el("button", { class: cls, text: label });
          b.addEventListener("click", async () => {
            const auth = getAuth();
            b.disabled = true;
            b.textContent = "Processing…";
            msg.innerHTML = "";
            msg.appendChild(el("div", { class: "help-text", text:
              "The decision is applied by a background workflow, not instantly — this waits up to a few seconds for it to settle." }));
            try {
              await api(`/requests/${req.request_id}/${decision}`, {
                method: "POST",
                body: JSON.stringify({ decided_by: approverInput.value, comments: `${decision}d by ${auth.email} via demo UI` }),
              });
              // Async: the decision is applied by a Temporal workflow signal,
              // not by this call returning — poll briefly instead of trusting
              // an immediate re-fetch.
              let settled = false;
              for (let i = 0; i < 10; i++) {
                await new Promise((res) => setTimeout(res, 500));
                const check = await api(`/requests/${req.request_id}`);
                if (check.data.status !== "pending_approval") { settled = true; break; }
              }
              msg.innerHTML = "";
              msg.appendChild(okBanner(settled ? `Request ${decision}d.` : `Request ${decision} submitted — still settling, reload the inbox in a moment.`));
              load();
            } catch (e) {
              msg.innerHTML = "";
              msg.appendChild(errorBanner(e.message));
              b.disabled = false;
              b.textContent = label;
            }
          });
          return b;
        };
        table.appendChild(el("tr", {}, [
          el("td", { text: req.request_id.slice(0, 8) + "…" }),
          el("td", { text: req.request_type }),
          el("td", { text: req.department }),
          el("td", { text: `${req.amount} ${req.currency}` }),
          el("td", {}, badge(req.spend_tier)),
          el("td", { text: req.sla_deadline ? new Date(req.sla_deadline).toLocaleString() : "—" }),
          el("td", {}, [decideBtn("approve", ""), document.createTextNode(" "), decideBtn("reject", "danger")]),
        ]));
      });
      out.appendChild(table);
    } catch (e) { out.innerHTML = ""; out.appendChild(errorBanner(e.message)); }
  }
  refreshBtn.addEventListener("click", load);

  // --- Create a request ---
  const createPanel = el("div", { class: "panel" });
  createPanel.appendChild(el("h2", { text: "Create a purchase request" }));
  createPanel.appendChild(el("p", { class: "desc", text: "Requires requester/admin role." }));
  const typeSel = el("select", {}, ["hardware", "license", "saas", "reclaim"].map((t) => el("option", { value: t, text: t })));
  const deptInput = el("input", { placeholder: "Department", value: "Engineering" });
  const amountInput = el("input", { type: "number", placeholder: "Amount", value: "1200" });
  const createBtn = el("button", { text: "Submit request" });
  createPanel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field" }, [el("label", { text: "Type" }), typeSel]),
    el("div", { class: "field" }, [el("label", { text: "Department" }), deptInput]),
    el("div", { class: "field" }, [el("label", { text: "Amount (INR)" }), amountInput]),
    createBtn,
  ]));
  const createMsg = el("div");
  createPanel.appendChild(createMsg);
  root.appendChild(createPanel);

  createBtn.addEventListener("click", async () => {
    createMsg.innerHTML = "";
    const auth = getAuth();
    try {
      const r = await api("/requests/", {
        method: "POST",
        body: JSON.stringify({
          request_type: typeSel.value, requested_by: auth.email, department: deptInput.value,
          amount: Number(amountInput.value), currency: "INR",
        }),
      });
      createMsg.appendChild(okBanner(`Created — status: ${r.data.status}, tier: ${r.data.spend_tier}.`));
    } catch (e) { createMsg.appendChild(errorBanner(e.message)); }
  });
}

// ---------- Document Review ----------

async function renderDocuments() {
  const root = document.getElementById("tab-documents");
  root.innerHTML = "";

  root.appendChild(el("div", { class: "help-text", html:
    "<strong>Pipeline:</strong> upload → ClamAV malware scan → stored in MinIO → a background worker " +
    "parses it (native text or OCR for scans), classifies PO/invoice/quote, extracts fields, and fuzzy-" +
    "matches the vendor. Anything below the confidence threshold lands in the review queue below instead " +
    "of auto-completing. No sample file handy? The repo ships ~20 synthetic ones under " +
    "<code>data/synthetic-invoices/</code>." }));

  const uploadPanel = el("div", { class: "panel" });
  uploadPanel.appendChild(el("h2", { text: "Upload a document" }));
  uploadPanel.appendChild(el("p", { class: "desc", text: "PO, invoice, or vendor quote (PDF/image). Scanned through ClamAV, stored in MinIO, then classified/extracted by the worker." }));
  const fileInput = el("input", { type: "file" });
  const uploadBtn = el("button", { text: "Upload" });
  uploadPanel.appendChild(el("div", { class: "row" }, [el("div", { class: "field" }, fileInput), uploadBtn]));
  const uploadMsg = el("div");
  uploadPanel.appendChild(uploadMsg);
  root.appendChild(uploadPanel);

  uploadBtn.addEventListener("click", async () => {
    uploadMsg.innerHTML = "";
    if (!fileInput.files.length) { uploadMsg.appendChild(errorBanner("Choose a file first.")); return; }
    const auth = getAuth();
    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    fd.append("uploaded_by", auth.email);
    try {
      const r = await apiUpload("/documents/upload", fd);
      uploadMsg.appendChild(okBanner(`Uploaded — document_id ${r.data.document_id}. Extraction runs in the background; refresh the queue below shortly.`));
    } catch (e) { uploadMsg.appendChild(errorBanner(e.message)); }
  });

  const panel = el("div", { class: "panel" });
  panel.appendChild(el("h2", { text: "Review queue" }));
  panel.appendChild(el("p", { class: "desc", text: "Documents below the confidence threshold — correct and resubmit." }));
  const refreshBtn = el("button", { class: "secondary", text: "Refresh" });
  panel.appendChild(refreshBtn);
  const out = el("div", { class: "empty", text: "Click refresh." });
  panel.appendChild(out);
  root.appendChild(panel);

  async function load() {
    out.innerHTML = "Loading…";
    try {
      const r = await api("/documents/review-queue");
      if (!r.data.length) { out.innerHTML = ""; out.appendChild(el("div", { class: "empty", text: "Nothing needs review right now." })); return; }
      out.innerHTML = "";
      r.data.forEach((doc) => out.appendChild(renderDocCard(doc)));
    } catch (e) { out.innerHTML = ""; out.appendChild(errorBanner(e.message)); }
  }
  refreshBtn.addEventListener("click", load);

  function renderDocCard(doc) {
    const card = el("div", { class: "panel", style: "background:var(--panel-2)" });
    card.appendChild(el("div", { class: "row" }, [
      el("div", {}, [el("div", { class: "small muted", text: "Document" }), el("div", { text: doc.id })]),
      el("div", {}, [el("div", { class: "small muted", text: "Type" }), badge(doc.document_type || "unclassified")]),
      el("div", {}, [el("div", { class: "small muted", text: "Confidence" }), el("div", { text: (doc.overall_confidence ?? 0).toFixed(2) })]),
    ]));
    const vendorInput = el("input", { placeholder: "Corrected vendor name", value: doc.vendor_name_raw || "" });
    const totalInput = el("input", { placeholder: "Corrected total", value: (doc.extracted_fields && doc.extracted_fields.total) || "" });
    const saveBtn = el("button", { text: "Save correction" });
    card.appendChild(el("div", { class: "row" }, [
      el("div", { class: "field" }, [el("label", { text: "Vendor name" }), vendorInput]),
      el("div", { class: "field" }, [el("label", { text: "Total" }), totalInput]),
      saveBtn,
    ]));
    const cardMsg = el("div");
    card.appendChild(cardMsg);

    saveBtn.addEventListener("click", async () => {
      cardMsg.innerHTML = "";
      const auth = getAuth();
      const corrected = Object.assign({}, doc.extracted_fields || {}, { total: totalInput.value ? Number(totalInput.value) : null });
      try {
        await api(`/documents/${doc.id}/review`, {
          method: "POST",
          body: JSON.stringify({
            reviewed_by: auth.email,
            vendor_name: vendorInput.value,
            extracted_fields: corrected,
            document_type: doc.document_type || "invoice",
          }),
        });
        cardMsg.appendChild(okBanner("Correction saved."));
      } catch (e) { cardMsg.appendChild(errorBanner(e.message)); }
    });
    return card;
  }
}

// ---------- Boot ----------

(function boot() {
  const auth = getAuth();
  if (auth && auth.access_token) showApp();
  else showLogin();
})();
