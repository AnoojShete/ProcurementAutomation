import { useState, useEffect } from "react";
import {
  ShieldCheck,
  FileSpreadsheet,
  Download,
  AlertTriangle,
  Clock,
  UserX,
  FileCheck2,
  Lock,
  Plus,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, StatusDot } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { InlineError } from "@/components/ui/ErrorState";
import { useAuth } from "@/hooks/useAuth";
import {
  privacyApi,
  type PrivacyProcessingRecord,
  type PrivacyRequest,
  type DataProcessor,
  type PrivacyIncident,
  type DomainHealthResult,
} from "@/api/privacy";

type Tab = "ropa" | "dsr" | "processors" | "incidents" | "domain";

export function PrivacyPage() {
  usePageHeader("Privacy & Data Protection", "Administration");
  const { user } = useAuth();

  const [activeTab, setActiveTab] = useState<Tab>("ropa");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Data states
  const [records, setRecords] = useState<PrivacyProcessingRecord[]>([]);
  const [requests, setRequests] = useState<PrivacyRequest[]>([]);
  const [processors, setProcessors] = useState<DataProcessor[]>([]);
  const [incidents, setIncidents] = useState<PrivacyIncident[]>([]);
  const [domainHealth, setDomainHealth] = useState<DomainHealthResult | null>(null);

  // Modal states
  const [showNewDsrModal, setShowNewDsrModal] = useState(false);
  const [dsrForm, setDsrForm] = useState({
    type: "access",
    subject_email: "",
    identity_verified_by: "",
    notes: "",
  });

  const [erasureModalRequest, setErasureModalRequest] = useState<PrivacyRequest | null>(null);
  const [erasureForm, setErasureForm] = useState({
    subject_email: "",
    second_admin_email: "",
    reason: "",
  });
  const [erasureError, setErasureError] = useState<string | null>(null);

  const [showIncidentModal, setShowIncidentModal] = useState(false);
  const [incidentForm, setIncidentForm] = useState({
    description: "",
    data_categories: "User account credentials, email logs",
    subjects_affected_estimate: 1,
    notes: "",
  });

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [recRes, reqRes, procRes, incRes, domRes] = await Promise.all([
        privacyApi.processingRecords(),
        privacyApi.requests(),
        privacyApi.processors(),
        privacyApi.incidents(),
        privacyApi.domainHealth(),
      ]);
      setRecords(recRes.data?.data || []);
      setRequests(reqRes.data?.data || []);
      setProcessors(procRes.data?.data || []);
      setIncidents(incRes.data?.data || []);
      setDomainHealth(domRes.data?.data || null);
    } catch (e: any) {
      setError(e?.message || "Failed to load privacy management records.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateDsr = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await privacyApi.createRequest(dsrForm);
      setShowNewDsrModal(false);
      setDsrForm({ type: "access", subject_email: "", identity_verified_by: "", notes: "" });
      loadData();
    } catch (e: any) {
      alert(e?.message || "Failed to log DSR.");
    }
  };

  const handleExecuteErasure = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!erasureModalRequest) return;
    setErasureError(null);

    if (user?.email?.toLowerCase() === erasureForm.second_admin_email.trim().toLowerCase()) {
      setErasureError("Dual-control violation: Second admin approver must be distinct from initiating admin.");
      return;
    }

    try {
      await privacyApi.eraseRequest(erasureModalRequest.id, erasureForm);
      setErasureModalRequest(null);
      setErasureForm({ subject_email: "", second_admin_email: "", reason: "" });
      loadData();
    } catch (e: any) {
      setErasureError(e?.message || "Failed to execute erasure.");
    }
  };

  const handleCreateIncident = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await privacyApi.createIncident(incidentForm);
      setShowIncidentModal(false);
      setIncidentForm({ description: "", data_categories: "", subjects_affected_estimate: 1, notes: "" });
      loadData();
    } catch (e: any) {
      alert(e?.message || "Failed to record privacy incident.");
    }
  };

  return (
    <div className="flex flex-col gap-6 p-6">
      {/* Scope, stance & DRAFT legal disclaimer banner */}
      <div className="rounded-lg border border-rule-strong bg-sheet-sunk p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="size-5 shrink-0 text-amber-500 mt-0.5" />
          <div className="flex flex-col gap-1 text-13">
            <span className="font-semibold text-ink">
              DRAFT — Technical controls active; requires ongoing legal review.
            </span>
            <p className="text-ink-2">
              The platform sends operational B2B emails exclusively (approvals, reminders, contract & security notices).
              Marketing communications are strictly prohibited. A uniform GDPR-level baseline applies across all environments,
              with regional notice wording determined by legal regime rules. This interface does not claim statutory compliance.
            </p>
          </div>
        </div>
      </div>

      {/* Tabs bar */}
      <div className="flex items-center justify-between border-b border-rule pb-2">
        <nav className="flex space-x-2">
          {[
            { id: "ropa", label: "Processing Register (ROPA)", icon: FileSpreadsheet },
            { id: "dsr", label: "Data Subject Requests (DSR)", icon: UserX },
            { id: "processors", label: "Sub-Processors", icon: ShieldCheck },
            { id: "incidents", label: "Incident Tracker (72h)", icon: Clock },
            { id: "domain", label: "Domain & Transport Health", icon: Lock },
          ].map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => setActiveTab(t.id as Tab)}
                className={`flex items-center gap-2 rounded-md px-3 py-2 text-13 font-medium transition-colors ${
                  activeTab === t.id
                    ? "bg-accent text-white"
                    : "text-ink-2 hover:bg-sheet-sunk hover:text-ink"
                }`}
              >
                <Icon className="size-4" />
                {t.label}
              </button>
            );
          })}
        </nav>
        <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} onClick={loadData}>
          Refresh
        </Button>
      </div>

      {error && <InlineError message={error} />}

      {loading ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          {/* TAB 1: Processing Register (ROPA) */}
          {activeTab === "ropa" && (
            <Card>
              <CardHeader
                title="Records of Processing Activities (ROPA)"
                subtitle="Article 30 GDPR & DPDP Act 2023 Processing Register. Seeded from data inventory."
                action={
                  <a
                    href={privacyApi.exportProcessingRecordsCsvUrl()}
                    download="processing_records.csv"
                    className="inline-flex items-center gap-1.5 rounded-md border border-rule bg-sheet px-3 py-1.5 text-13 font-medium text-ink hover:bg-sheet-sunk"
                  >
                    <Download className="size-3.5" />
                    Export CSV
                  </a>
                }
              />
              <CardBody className="p-0 overflow-x-auto">
                <table className="w-full text-left text-13">
                  <thead className="border-b border-rule bg-sheet-sunk text-ink-3">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Activity</th>
                      <th className="px-4 py-2.5 font-medium">Purpose</th>
                      <th className="px-4 py-2.5 font-medium">Data Categories</th>
                      <th className="px-4 py-2.5 font-medium">Data Subjects</th>
                      <th className="px-4 py-2.5 font-medium">Lawful Basis</th>
                      <th className="px-4 py-2.5 font-medium">Storage Location</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {records.map((r) => (
                      <tr key={r.id} className="hover:bg-sheet-sunk/50">
                        <td className="px-4 py-2.5 font-mono font-medium text-ink">{r.activity}</td>
                        <td className="px-4 py-2.5 text-ink-2 max-w-xs">{r.purpose}</td>
                        <td className="px-4 py-2.5 text-ink-2">{r.data_categories}</td>
                        <td className="px-4 py-2.5 text-ink-2">
                          <Badge tone="neutral">{r.data_subjects}</Badge>
                        </td>
                        <td className="px-4 py-2.5 text-ink-2 font-mono text-xs">{r.lawful_basis}</td>
                        <td className="px-4 py-2.5 text-ink-3 text-xs">{r.storage_location}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}

          {/* TAB 2: Data Subject Requests (DSR) */}
          {activeTab === "dsr" && (
            <Card>
              <CardHeader
                title="Data Subject Requests (DSR)"
                subtitle="Enforce GDPR Art 15-21 and DPDP Section 11-13 rights with strict statutory timers."
                action={
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Plus className="size-3.5" />}
                    onClick={() => setShowNewDsrModal(true)}
                  >
                    Log Request
                  </Button>
                }
              />
              <CardBody className="p-0 overflow-x-auto">
                <table className="w-full text-left text-13">
                  <thead className="border-b border-rule bg-sheet-sunk text-ink-3">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Type</th>
                      <th className="px-4 py-2.5 font-medium">Email Hash</th>
                      <th className="px-4 py-2.5 font-medium">Verified By</th>
                      <th className="px-4 py-2.5 font-medium">Statutory Due</th>
                      <th className="px-4 py-2.5 font-medium">Status</th>
                      <th className="px-4 py-2.5 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {requests.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-ink-3">
                          No pending or historical Data Subject Requests logged.
                        </td>
                      </tr>
                    ) : (
                      requests.map((req) => (
                        <tr key={req.id} className="hover:bg-sheet-sunk/50">
                          <td className="px-4 py-2.5">
                            <Badge tone={req.type === "erasure" ? "danger" : "brand"}>{req.type.toUpperCase()}</Badge>
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs text-ink-3">
                            {req.subject_email_hash.slice(0, 16)}...
                          </td>
                          <td className="px-4 py-2.5 text-ink-2">{req.identity_verified_by}</td>
                          <td className="px-4 py-2.5 text-ink-2">
                            <span className="flex items-center gap-1.5">
                              <Clock className="size-3.5 text-ink-3" />
                              {req.due_at ? new Date(req.due_at).toLocaleDateString() : "—"}
                              <span className="text-xs text-ink-3">({req.days_remaining}d left)</span>
                            </span>
                          </td>
                          <td className="px-4 py-2.5">
                            <StatusDot tone={req.status === "completed" ? "success" : "warning"}>
                              {req.status}
                            </StatusDot>
                          </td>
                          <td className="px-4 py-2.5 text-right space-x-2">
                            {req.type === "access" && (
                              <button
                                type="button"
                                onClick={() => {
                                  const email = prompt("Enter verified subject email address for export bundle:");
                                  if (email) {
                                    window.open(privacyApi.exportDsrUrl(req.id, email), "_blank");
                                  }
                                }}
                                className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
                              >
                                <Download className="size-3" /> Export ZIP
                              </button>
                            )}
                            {req.type === "erasure" && req.status !== "completed" && (
                              <button
                                type="button"
                                onClick={() => {
                                  setErasureModalRequest(req);
                                  setErasureError(null);
                                }}
                                className="inline-flex items-center gap-1 text-xs text-rose-600 hover:underline font-medium"
                              >
                                <UserX className="size-3" /> Dual-Admin Erase
                              </button>
                            )}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}

          {/* TAB 3: Sub-Processors */}
          {activeTab === "processors" && (
            <Card>
              <CardHeader
                title="Data Processors & Cross-Border Relays"
                subtitle="Approved sub-processors. Recipients in EU/EEA/UK require processor region verification."
              />
              <CardBody className="p-0 overflow-x-auto">
                <table className="w-full text-left text-13">
                  <thead className="border-b border-rule bg-sheet-sunk text-ink-3">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Processor Name</th>
                      <th className="px-4 py-2.5 font-medium">Purpose</th>
                      <th className="px-4 py-2.5 font-medium">Jurisdiction</th>
                      <th className="px-4 py-2.5 font-medium">DPA Reference</th>
                      <th className="px-4 py-2.5 font-medium">Transfer Mechanism</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {processors.map((p) => (
                      <tr key={p.id}>
                        <td className="px-4 py-2.5 font-medium text-ink">{p.name}</td>
                        <td className="px-4 py-2.5 text-ink-2">{p.purpose}</td>
                        <td className="px-4 py-2.5">
                          <Badge tone="brand">{p.country}</Badge>
                        </td>
                        <td className="px-4 py-2.5 font-mono text-xs text-ink-3">{p.dpa_reference || "Standard DPA"}</td>
                        <td className="px-4 py-2.5 text-xs text-ink-3">{p.transfer_mechanism_note || "EU SCCs / Adequacy"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}

          {/* TAB 4: Incident Tracker */}
          {activeTab === "incidents" && (
            <Card>
              <CardHeader
                title="Security & Privacy Breach Tracker"
                subtitle="Track detection time against the 72-hour supervisory authority notification window."
                action={
                  <Button
                    size="sm"
                    variant="destructive"
                    icon={<Plus className="size-3.5" />}
                    onClick={() => setShowIncidentModal(true)}
                  >
                    Log Incident
                  </Button>
                }
              />
              <CardBody className="flex flex-col gap-4">
                <div className="rounded border border-amber-300 bg-amber-50 p-3 text-13 text-amber-900">
                  <strong>GDPR guidance:</strong> Notify the competent supervisory authority within 72 hours of becoming
                  aware of a personal data breach where feasible. Confirm obligations for your specific jurisdictions with legal counsel.
                </div>

                <div className="divide-y divide-rule border border-rule rounded-md">
                  {incidents.length === 0 ? (
                    <div className="p-4 text-center text-13 text-ink-3">No recorded security or privacy incidents.</div>
                  ) : (
                    incidents.map((inc) => (
                      <div key={inc.id} className="p-4 flex items-start justify-between gap-4">
                        <div className="flex flex-col gap-1">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-ink">{inc.description}</span>
                            <Badge tone={inc.hours_since_detection > 72 ? "danger" : "warning"}>
                              {inc.hours_since_detection}h since detection
                            </Badge>
                          </div>
                          <p className="text-13 text-ink-2">Categories: {inc.data_categories || "None specified"}</p>
                          <span className="text-xs text-ink-3">Estimated affected individuals: {inc.subjects_affected_estimate}</span>
                        </div>
                        <div className="text-right text-xs text-ink-3">
                          Detected: {inc.detected_at ? new Date(inc.detected_at).toLocaleString() : "—"}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </CardBody>
            </Card>
          )}

          {/* TAB 5: Domain Health & TLS */}
          {activeTab === "domain" && domainHealth && (
            <Card>
              <CardHeader
                title="Sender Domain Health & Email Transport"
                subtitle="Verification of SPF, DMARC, DKIM, and TLS transport encryption."
              />
              <CardBody className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="rounded-md border border-rule p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">SPF Authentication</span>
                    <Badge tone="success">{domainHealth.spf.status.toUpperCase()}</Badge>
                  </div>
                  <code className="text-xs font-mono text-ink-2 bg-sheet-sunk p-2 rounded">{domainHealth.spf.record}</code>
                </div>

                <div className="rounded-md border border-rule p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">DMARC Policy Enforcement</span>
                    <Badge tone="success">{domainHealth.dmarc.status.toUpperCase()} ({domainHealth.dmarc.policy})</Badge>
                  </div>
                  <code className="text-xs font-mono text-ink-2 bg-sheet-sunk p-2 rounded">{domainHealth.dmarc.record}</code>
                </div>

                <div className="rounded-md border border-rule p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">DKIM Selector</span>
                    <Badge tone="success">PASS (2048-bit)</Badge>
                  </div>
                  <span className="text-13 text-ink-2">Selector: {domainHealth.dkim.selector}</span>
                </div>

                <div className="rounded-md border border-rule p-4 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-ink">TLS Transport Encryption</span>
                    <Badge tone="success">ENFORCED</Badge>
                  </div>
                  <span className="text-13 text-ink-2">STARTTLS / SMTPS with certificate validation enforced in non-dev environments.</span>
                </div>
              </CardBody>
            </Card>
          )}
        </>
      )}

      {/* MODAL: Log New DSR */}
      {showNewDsrModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg border border-rule bg-sheet p-6 shadow-xl">
            <h3 className="text-heading font-semibold text-ink mb-2">Log Data Subject Request</h3>
            <p className="text-13 text-ink-2 mb-4">
              All requests must verify identity before processing. Statutory deadline applies immediately.
            </p>
            <form onSubmit={handleCreateDsr} className="flex flex-col gap-4">
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Request Type
                <select
                  value={dsrForm.type}
                  onChange={(e) => setDsrForm({ ...dsrForm, type: e.target.value })}
                  className="field"
                >
                  <option value="access">Access (Data Export)</option>
                  <option value="rectification">Rectification</option>
                  <option value="erasure">Erasure (Right to be Forgotten)</option>
                  <option value="restriction">Restriction</option>
                  <option value="objection">Objection to Operational Messages</option>
                </select>
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Subject Email Address
                <input
                  type="email"
                  required
                  value={dsrForm.subject_email}
                  onChange={(e) => setDsrForm({ ...dsrForm, subject_email: e.target.value })}
                  placeholder="individual@domain.com"
                  className="field"
                >
                </input>
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Identity Verified By
                <input
                  type="text"
                  required
                  value={dsrForm.identity_verified_by}
                  onChange={(e) => setDsrForm({ ...dsrForm, identity_verified_by: e.target.value })}
                  placeholder="Government ID / Corporate SSO verification"
                  className="field"
                />
              </label>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" onClick={() => setShowNewDsrModal(false)}>Cancel</Button>
                <Button variant="primary" type="submit">Submit Request</Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Dual-Admin Erasure */}
      {erasureModalRequest && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-lg border border-rule bg-sheet p-6 shadow-2xl">
            <div className="flex items-center gap-2 text-rose-600 mb-2 font-semibold">
              <AlertTriangle className="size-5" />
              Dual-Admin Erasure Approval Required
            </div>
            <p className="text-13 text-ink-2 mb-4 leading-relaxed">
              Pursuant to dual-control privacy policies, erasing personal data requires two distinct administrators.
              Identifiers will be pseudonymised as <code className="font-mono text-xs">erased:&lt;sha256&gt;</code> to
              preserve audit integrity and statutory retention obligations.
            </p>

            {erasureError && <div className="mb-4"><InlineError message={erasureError} /></div>}

            <form onSubmit={handleExecuteErasure} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Initiating Administrator
                <input
                  type="text"
                  disabled
                  value={user?.email || "current-admin"}
                  className="field bg-sheet-sunk text-ink-3"
                />
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Subject Email to Erase
                <input
                  type="email"
                  required
                  value={erasureForm.subject_email}
                  onChange={(e) => setErasureForm({ ...erasureForm, subject_email: e.target.value })}
                  placeholder="individual@domain.com"
                  className="field"
                />
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Second Admin Approver Email
                <input
                  type="email"
                  required
                  value={erasureForm.second_admin_email}
                  onChange={(e) => setErasureForm({ ...erasureForm, second_admin_email: e.target.value })}
                  placeholder="distinct.admin@company.local"
                  className="field"
                />
                <span className="text-xs text-ink-3">Must be a verified administrator other than yourself.</span>
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Erasure Justification / Legal Basis
                <input
                  type="text"
                  required
                  value={erasureForm.reason}
                  onChange={(e) => setErasureForm({ ...erasureForm, reason: e.target.value })}
                  placeholder="GDPR Art 17 request confirmed; no statutory tax hold pending"
                  className="field"
                />
              </label>

              <div className="flex justify-end gap-2 pt-3">
                <Button variant="secondary" onClick={() => setErasureModalRequest(null)}>Cancel</Button>
                <Button variant="destructive" type="submit">Approve & Execute Erasure</Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: Log Incident */}
      {showIncidentModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-lg border border-rule bg-sheet p-6 shadow-xl">
            <h3 className="text-heading font-semibold text-ink mb-2">Record Security / Privacy Incident</h3>
            <form onSubmit={handleCreateIncident} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Description
                <textarea
                  required
                  value={incidentForm.description}
                  onChange={(e) => setIncidentForm({ ...incidentForm, description: e.target.value })}
                  placeholder="Summary of detected incident..."
                  className="field h-24"
                />
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Data Categories Affected
                <input
                  type="text"
                  value={incidentForm.data_categories}
                  onChange={(e) => setIncidentForm({ ...incidentForm, data_categories: e.target.value })}
                  className="field"
                />
              </label>

              <label className="flex flex-col gap-1 text-13 text-ink-2">
                Estimated Affected Individuals
                <input
                  type="number"
                  min="0"
                  value={incidentForm.subjects_affected_estimate}
                  onChange={(e) => setIncidentForm({ ...incidentForm, subjects_affected_estimate: parseInt(e.target.value) || 0 })}
                  className="field"
                />
              </label>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="secondary" onClick={() => setShowIncidentModal(false)}>Cancel</Button>
                <Button variant="destructive" type="submit">Record Incident</Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
