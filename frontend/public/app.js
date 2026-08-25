// Vanilla JS, no build step — every fetch goes through the gateway at
// /api/* (same origin as this page, served by the nginx container), so
// there's no CORS to configure and no separate frontend port to keep in
// sync with the gateway's routing table.
const API_BASE = "/api";
const AUTH_KEY = "itpip_auth";

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
  document.getElementById("who-label").textContent = `${auth.email} · ${auth.role}`;
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

// ---------- Tabs ----------

const TAB_RENDERERS = { overview: renderOverview, contracts: renderContracts, approvals: renderApprovals, documents: renderDocuments };
let activeTab = "overview";

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

// ---------- Overview ----------

async function renderOverview() {
  const root = document.getElementById("tab-overview");
  root.innerHTML = "";
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
  panel.appendChild(el("p", { class: "desc", text: "Pending requests routed to an approver role (e.g. dept_manager, finance_head — per config.yaml's spend-tier chains, not an individual user id)." }));
  const approverInput = el("input", { value: "dept_manager" });
  const refreshBtn = el("button", { text: "Load inbox" });
  panel.appendChild(el("div", { class: "row" }, [
    el("div", { class: "field", style: "flex:0;min-width:200px" }, [el("label", { text: "Approver role" }), approverInput]),
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
          const b = el("button", { class: cls, text: decision === "approve" ? "Approve" : "Reject" });
          b.addEventListener("click", async () => {
            const auth = getAuth();
            try {
              await api(`/requests/${req.request_id}/${decision}`, {
                method: "POST",
                body: JSON.stringify({ decided_by: approverInput.value.trim(), comments: `${decision}d by ${auth.email} via demo UI` }),
              });
              msg.innerHTML = ""; msg.appendChild(okBanner(`Request ${decision}d.`));
              load();
            } catch (e) { msg.innerHTML = ""; msg.appendChild(errorBanner(e.message)); }
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
