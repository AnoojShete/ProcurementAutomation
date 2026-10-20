import { useState, useEffect } from "react";
import {
  ShieldAlert,
  Play,
  CheckCircle,
  AlertTriangle,
  History,
  FileCode,
  Download,
  Copy,
  Save,
  Rocket,
  Info,
  Clock,
  Layers,
} from "lucide-react";
import { rulesetsApi } from "@/api/vendors";
import type { RulesetResponse, DryRunReport } from "@/types/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";

export function RiskRulesetGovernance() {
  const [activeTab, setActiveTab] = useState<"active" | "draft" | "history">("active");
  const [activeRuleset, setActiveRuleset] = useState<RulesetResponse | null>(null);
  const [draftRuleset, setDraftRuleset] = useState<RulesetResponse | null>(null);
  const [history, setHistory] = useState<RulesetResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Draft editing state
  const [draftJson, setDraftJson] = useState<string>("");
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors: string[] } | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSavingDraft, setIsSavingDraft] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  // Dry run state
  const [dryRunModalOpen, setDryRunModalOpen] = useState(false);
  const [dryRunSampleSize, setDryRunSampleSize] = useState(100);
  const [isRunningDryRun, setIsRunningDryRun] = useState(false);
  const [dryRunReport, setDryRunReport] = useState<DryRunReport | null>(null);
  const [dryRunError, setDryRunError] = useState<string | null>(null);

  // Activation modal state
  const [activateModalOpen, setActivateModalOpen] = useState(false);
  const [changeJustification, setChangeJustification] = useState("");
  const [isActivating, setIsActivating] = useState(false);
  const [activateError, setActivateError] = useState<string | null>(null);

  const fetchActiveAndDraft = async () => {
    try {
      setLoading(true);
      setError(null);
      const [activeRes, draftRes, historyRes] = await Promise.allSettled([
        rulesetsApi.active(),
        rulesetsApi.draft(),
        rulesetsApi.history(),
      ]);

      if (activeRes.status === "fulfilled") {
        setActiveRuleset(activeRes.value.data);
      }
      if (draftRes.status === "fulfilled" && draftRes.value.data) {
        setDraftRuleset(draftRes.value.data);
        setDraftJson(JSON.stringify(draftRes.value.data.definition, null, 2));
      } else if (activeRes.status === "fulfilled" && activeRes.value.data) {
        // Default draft to clone of active if no draft exists
        setDraftJson(JSON.stringify(activeRes.value.data.definition, null, 2));
      }
      if (historyRes.status === "fulfilled") {
        setHistory(historyRes.value.data || []);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load risk rulesets");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchActiveAndDraft();
  }, []);

  const handleCloneActiveToDraft = () => {
    if (activeRuleset?.definition) {
      const cloned = JSON.parse(JSON.stringify(activeRuleset.definition));
      cloned.version = (activeRuleset.version || 1) + 1;
      setDraftJson(JSON.stringify(cloned, null, 2));
      setValidationResult(null);
      setSaveSuccess("Active ruleset cloned to draft editor.");
    }
  };

  const handleValidateDraft = async () => {
    setIsValidating(true);
    setValidationResult(null);
    try {
      const parsed = JSON.parse(draftJson);
      const res = await rulesetsApi.validate(parsed);
      setValidationResult(res.data);
    } catch (err: any) {
      setValidationResult({
        valid: false,
        errors: [`JSON Syntax Error: ${err.message}`],
      });
    } finally {
      setIsValidating(false);
    }
  };

  const handleSaveDraft = async () => {
    setIsSavingDraft(true);
    setSaveSuccess(null);
    try {
      const parsed = JSON.parse(draftJson);
      const res = await rulesetsApi.saveDraft(parsed);
      setDraftRuleset(res.data);
      setSaveSuccess("Draft saved successfully.");
    } catch (err: any) {
      setError(err?.message || "Failed to save draft");
    } finally {
      setIsSavingDraft(false);
    }
  };

  const handleRunDryRun = async () => {
    setIsRunningDryRun(true);
    setDryRunError(null);
    try {
      const parsed = JSON.parse(draftJson);
      const res = await rulesetsApi.dryRun(parsed, dryRunSampleSize);
      setDryRunReport(res.data);
    } catch (err: any) {
      setDryRunError(err?.message || "Dry run execution failed");
    } finally {
      setIsRunningDryRun(false);
    }
  };

  const handleActivate = async () => {
    if (changeJustification.trim().length < 20) {
      setActivateError("Justification must be at least 20 characters.");
      return;
    }
    setIsActivating(true);
    setActivateError(null);
    try {
      const parsed = JSON.parse(draftJson);
      await rulesetsApi.activate(parsed, changeJustification.trim());
      setActivateModalOpen(false);
      setChangeJustification("");
      await fetchActiveAndDraft();
      setActiveTab("active");
    } catch (err: any) {
      setActivateError(err?.message || "Failed to activate ruleset");
    } finally {
      setIsActivating(false);
    }
  };

  const downloadRulesetJson = (ruleset: RulesetResponse) => {
    const blob = new Blob([JSON.stringify(ruleset.definition, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `risk-ruleset-v${ruleset.version}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header / Subtabs */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-3">
        <div className="flex gap-2">
          <Button
            variant={activeTab === "active" ? "primary" : "secondary"}
            size="sm"
            onClick={() => setActiveTab("active")}
          >
            <ShieldAlert className="size-4 mr-1.5" />
            Active Ruleset (v{activeRuleset?.version || 1})
          </Button>
          <Button
            variant={activeTab === "draft" ? "primary" : "secondary"}
            size="sm"
            onClick={() => setActiveTab("draft")}
          >
            <FileCode className="size-4 mr-1.5" />
            Edit Draft
          </Button>
          <Button
            variant={activeTab === "history" ? "primary" : "secondary"}
            size="sm"
            onClick={() => setActiveTab("history")}
          >
            <History className="size-4 mr-1.5" />
            Version History ({history.length})
          </Button>
        </div>

        {activeRuleset && (
          <div className="flex items-center gap-2 text-xs text-ink-3">
            <span>Active since: {formatDateTime(activeRuleset.activated_at || activeRuleset.created_at)}</span>
            <span>•</span>
            <span>Hash: <code className="font-mono">{activeRuleset.definition_hash?.substring(0, 10)}...</code></span>
          </div>
        )}
      </div>

      {error && <InlineError message={error} />}

      {/* ACTIVE TAB */}
      {activeTab === "active" && activeRuleset && (
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader
              title={`Active Ruleset Version ${activeRuleset.version}`}
              subtitle={
                activeRuleset.change_justification
                  ? `Justification: "${activeRuleset.change_justification}"`
                  : "Current production vendor risk scoring logic"
              }
              action={
                <div className="flex gap-2">
                  <Button variant="secondary" size="sm" onClick={() => downloadRulesetJson(activeRuleset)}>
                    <Download className="size-3.5 mr-1" /> Download JSON
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => { handleCloneActiveToDraft(); setActiveTab("draft"); }}>
                    <Copy className="size-3.5 mr-1" /> Clone to Draft
                  </Button>
                </div>
              }
            />
            <CardBody>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <div className="p-3 bg-sheet-subtle rounded-lg border border-rule">
                  <span className="text-caption text-ink-3">Status</span>
                  <p className="mt-1 font-semibold text-success-600 uppercase text-xs">Active (Immutable)</p>
                </div>
                <div className="p-3 bg-sheet-subtle rounded-lg border border-rule">
                  <span className="text-caption text-ink-3">Activated By</span>
                  <p className="mt-1 font-semibold text-ink text-xs">{activeRuleset.activated_by || "System Initializer"}</p>
                </div>
                <div className="p-3 bg-sheet-subtle rounded-lg border border-rule">
                  <span className="text-caption text-ink-3">Risk Bands</span>
                  <p className="mt-1 text-xs text-ink">
                    Low: ≤ {activeRuleset.definition?.bands?.low_max || 24} pts | Med: ≤ {activeRuleset.definition?.bands?.medium_max || 49} pts
                  </p>
                </div>
                <div className="p-3 bg-sheet-subtle rounded-lg border border-rule">
                  <span className="text-caption text-ink-3">Total Signals</span>
                  <p className="mt-1 font-semibold text-ink text-xs">
                    {activeRuleset.definition?.signals?.length || 0} signals (Sum = 100 pts)
                  </p>
                </div>
              </div>

              <div className="overflow-x-auto border border-rule rounded-lg">
                <table className="min-w-full text-xs text-left divide-y divide-rule">
                  <thead className="bg-sheet-subtle text-ink-2 font-medium">
                    <tr>
                      <th className="px-3 py-2">Signal & Group</th>
                      <th className="px-3 py-2">Max Pts</th>
                      <th className="px-3 py-2">TTL</th>
                      <th className="px-3 py-2">Rule Outcomes & Rationale</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {activeRuleset.definition?.signals?.map((sig: any) => (
                      <tr key={sig.key} className="align-top hover:bg-sheet-subtle/50">
                        <td className="px-3 py-2.5 font-medium text-ink whitespace-nowrap">
                          {sig.label || sig.key}
                          <div className="text-caption text-ink-3 font-normal uppercase">{sig.group}</div>
                        </td>
                        <td className="px-3 py-2.5 font-semibold text-ink tabular-nums">{sig.max_points}</td>
                        <td className="px-3 py-2.5 text-ink-2">{sig.ttl_days ? `${sig.ttl_days}d` : "None"}</td>
                        <td className="px-3 py-2.5 space-y-2">
                          {sig.outcomes?.map((out: any) => (
                            <div key={out.rule_id} className="p-2 rounded bg-sheet-subtle/80 border border-rule/50">
                              <div className="flex items-center justify-between gap-2">
                                <span className="font-mono font-bold text-ink-1">{out.rule_id}</span>
                                <div className="flex gap-1.5 items-center">
                                  {out.override_band && (
                                    <Badge tone="danger">Override: {out.override_band}</Badge>
                                  )}
                                  <Badge tone={out.points > 0 ? "warning" : "success"}>
                                    {out.points} pts ({out.status})
                                  </Badge>
                                  {out.remediable && (
                                    <span className="text-10 text-emerald-600 border border-emerald-300 px-1 rounded">remediable</span>
                                  )}
                                </div>
                              </div>
                              <p className="mt-1 text-ink-2 text-11 italic">{out.rationale}</p>
                              {out.reason && (
                                <p className="mt-0.5 text-ink-3 text-10 font-mono truncate">Template: {out.reason}</p>
                              )}
                            </div>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* DRAFT TAB */}
      {activeTab === "draft" && (
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader
              title="Draft Ruleset Editor"
              subtitle="Edit scorecard thresholds, point allocations, rule conditions, and expert rationales. Pre-publish checks ensure sum(max_points) == 100."
              action={
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" size="sm" onClick={handleCloneActiveToDraft}>
                    <Copy className="size-3.5 mr-1" /> Reset from Active
                  </Button>
                  <Button variant="secondary" size="sm" loading={isSavingDraft} onClick={handleSaveDraft}>
                    <Save className="size-3.5 mr-1" /> Save Draft
                  </Button>
                  <Button variant="secondary" size="sm" loading={isValidating} onClick={handleValidateDraft}>
                    <CheckCircle className="size-3.5 mr-1" /> Validate Ruleset
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setDryRunModalOpen(true)}>
                    <Play className="size-3.5 mr-1" /> Dry Run on Past Data
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => {
                      setActivateError(null);
                      setActivateModalOpen(true);
                    }}
                  >
                    <Rocket className="size-3.5 mr-1" /> Activate Ruleset...
                  </Button>
                </div>
              }
            />
            <CardBody className="space-y-4">
              {saveSuccess && <InlineSuccess message={saveSuccess} />}

              {validationResult && (
                <div className={`p-4 rounded-lg border text-sm ${validationResult.valid ? "bg-emerald-50 border-emerald-200 text-emerald-900" : "bg-rose-50 border-rose-200 text-rose-900"}`}>
                  <div className="flex items-center gap-2 font-semibold">
                    {validationResult.valid ? (
                      <>
                        <CheckCircle className="size-4 text-emerald-600" />
                        Ruleset Definition is Valid!
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="size-4 text-rose-600" />
                        Validation Failed ({validationResult.errors.length} errors)
                      </>
                    )}
                  </div>
                  {validationResult.valid ? (
                    <p className="mt-1 text-xs text-emerald-700">
                      All criteria satisfied: sum of max_points = 100, safe conditions verified, outcome order validated, unique rule IDs.
                    </p>
                  ) : (
                    <ul className="mt-2 list-inside list-disc text-xs space-y-1">
                      {validationResult.errors.map((e, idx) => (
                        <li key={idx} className="font-mono">{e}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              <div className="border border-rule rounded-lg overflow-hidden">
                <div className="bg-sheet-subtle px-4 py-2 border-b border-rule flex justify-between items-center text-xs text-ink-3">
                  <span className="font-medium text-ink">Ruleset JSON Definition</span>
                  <span>Pure declarative schema (No Python/Jinja/eval code permitted)</span>
                </div>
                <textarea
                  className="w-full h-[520px] font-mono text-xs p-4 bg-sheet text-ink focus:outline-none resize-y"
                  value={draftJson}
                  onChange={(e) => {
                    setDraftJson(e.target.value);
                    setValidationResult(null);
                  }}
                  spellCheck={false}
                />
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* HISTORY TAB */}
      {activeTab === "history" && (
        <Card>
          <CardHeader title="Ruleset Version History" subtitle="Audit trail of all published and retired ruleset versions." />
          <CardBody>
            <div className="overflow-x-auto border border-rule rounded-lg">
              <table className="min-w-full text-xs text-left divide-y divide-rule">
                <thead className="bg-sheet-subtle text-ink-2 font-medium">
                  <tr>
                    <th className="px-4 py-2.5">Version</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Activated At</th>
                    <th className="px-4 py-2.5">Activated By</th>
                    <th className="px-4 py-2.5">Justification</th>
                    <th className="px-4 py-2.5">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {history.map((r) => (
                    <tr key={r.id} className="hover:bg-sheet-subtle/50">
                      <td className="px-4 py-2.5 font-bold text-ink">v{r.version}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={r.status === "active" ? "success" : r.status === "draft" ? "warning" : "neutral"}>
                          {r.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-ink-2">{formatDateTime(r.activated_at || r.created_at)}</td>
                      <td className="px-4 py-2.5 text-ink">{r.activated_by || r.created_by || "System"}</td>
                      <td className="px-4 py-2.5 text-ink-2 max-w-xs truncate">{r.change_justification || "—"}</td>
                      <td className="px-4 py-2.5">
                        <Button variant="secondary" size="sm" onClick={() => downloadRulesetJson(r)}>
                          <Download className="size-3 mr-1" /> JSON
                        </Button>
                      </td>
                    </tr>
                  ))}
                  {history.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-ink-3">No history available yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {/* DRY RUN MODAL */}
      <Modal
        open={dryRunModalOpen}
        onClose={() => setDryRunModalOpen(false)}
        title="Dry Run Draft Ruleset on Historical Data"
        size="lg"
      >
        <div className="space-y-4">
          <p className="text-xs text-ink-2">
            Replays the draft ruleset against recent vendor assessments to simulate rating migrations and score shifts before publishing.
          </p>

          <div className="flex items-center gap-3">
            <label className="text-xs font-medium text-ink">Historical Sample Size:</label>
            <select
              className="text-xs border border-rule rounded px-2.5 py-1.5 bg-sheet text-ink"
              value={dryRunSampleSize}
              onChange={(e) => setDryRunSampleSize(Number(e.target.value))}
            >
              <option value={25}>25 latest assessments</option>
              <option value={50}>50 latest assessments</option>
              <option value={100}>100 latest assessments (standard)</option>
              <option value={200}>200 latest assessments</option>
            </select>
            <Button variant="primary" size="sm" loading={isRunningDryRun} onClick={handleRunDryRun}>
              <Play className="size-3 mr-1" /> Execute Simulation
            </Button>
          </div>

          {dryRunError && <InlineError message={dryRunError} />}

          {dryRunReport && (
            <div className="space-y-4 border-t border-rule pt-4 text-xs">
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 bg-sheet-subtle rounded border border-rule">
                  <span className="text-ink-3">Sample Evaluated</span>
                  <p className="font-semibold text-ink mt-0.5">{dryRunReport.sample_size} vendors</p>
                </div>
                <div className="p-3 bg-sheet-subtle rounded border border-rule">
                  <span className="text-ink-3">Execution Latency</span>
                  <p className="font-semibold text-ink mt-0.5">{dryRunReport.duration_ms} ms ({dryRunReport.avg_duration_ms} ms/vendor)</p>
                </div>
                <div className="p-3 bg-sheet-subtle rounded border border-rule">
                  <span className="text-ink-3">Band Changes</span>
                  <p className="font-semibold text-brand-600 mt-0.5">
                    {Object.values(dryRunReport.migration_matrix || {}).reduce((a, b) => a + b, 0)} migrations
                  </p>
                </div>
              </div>

              {/* Band Migration Matrix */}
              <div>
                <span className="font-semibold text-ink">Band Migration Matrix</span>
                <div className="mt-1 flex flex-wrap gap-2">
                  {Object.entries(dryRunReport.migration_matrix || {}).map(([mig, count]) => (
                    <div key={mig} className="px-2.5 py-1 rounded bg-slate-100 border border-slate-300 font-medium text-slate-800">
                      {mig}: <span className="font-bold">{count}</span>
                    </div>
                  ))}
                  {Object.keys(dryRunReport.migration_matrix || {}).length === 0 && (
                    <span className="text-ink-3 italic">No band migrations detected (all scores within same bands).</span>
                  )}
                </div>
              </div>

              {/* Top Movers */}
              <div>
                <span className="font-semibold text-ink">Top Score Movers</span>
                <div className="mt-1 border border-rule rounded overflow-hidden">
                  <table className="min-w-full text-xs text-left divide-y divide-rule">
                    <thead className="bg-sheet-subtle text-ink-2 font-medium">
                      <tr>
                        <th className="px-3 py-1.5">Vendor ID</th>
                        <th className="px-3 py-1.5">Active Points</th>
                        <th className="px-3 py-1.5">Draft Points</th>
                        <th className="px-3 py-1.5">Difference</th>
                        <th className="px-3 py-1.5">Band Shift</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {dryRunReport.top_movers?.map((m) => (
                        <tr key={m.vendor_id}>
                          <td className="px-3 py-1.5 font-mono text-ink-2">{m.vendor_id.substring(0, 8)}...</td>
                          <td className="px-3 py-1.5">{m.active_points} pts</td>
                          <td className="px-3 py-1.5">{m.draft_points} pts</td>
                          <td className={`px-3 py-1.5 font-bold ${m.diff > 0 ? "text-rose-600" : m.diff < 0 ? "text-emerald-600" : "text-ink-3"}`}>
                            {m.diff > 0 ? `+${m.diff}` : m.diff}
                          </td>
                          <td className="px-3 py-1.5">
                            {m.active_band} → <span className="font-semibold">{m.draft_band}</span>
                          </td>
                        </tr>
                      ))}
                      {(!dryRunReport.top_movers || dryRunReport.top_movers.length === 0) && (
                        <tr>
                          <td colSpan={5} className="px-3 py-2 text-ink-3 text-center">No movers in sample.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </Modal>

      {/* ACTIVATION MODAL */}
      <Modal
        open={activateModalOpen}
        onClose={() => setActivateModalOpen(false)}
        title="Activate Risk Scorecard Ruleset"
        size="md"
      >
        <div className="space-y-4">
          <p className="text-xs text-ink-2">
            Activating this ruleset will immediately put it into production for all future vendor risk assessments.
            Previous versions will be retired and preserved in the audit log.
          </p>

          <div>
            <label className="block text-xs font-semibold text-ink mb-1">
              Change Justification <span className="text-rose-500">*</span>
            </label>
            <textarea
              className="w-full text-xs p-2.5 border border-rule rounded bg-sheet text-ink focus:outline-none focus:ring-1 focus:ring-brand-500"
              rows={4}
              placeholder="Explain why these rules or point weights are being updated (minimum 20 characters)..."
              value={changeJustification}
              onChange={(e) => setChangeJustification(e.target.value)}
            />
            <div className="flex justify-between items-center text-11 mt-1 text-ink-3">
              <span>Required for auditability and compliance.</span>
              <span className={changeJustification.trim().length < 20 ? "text-rose-500" : "text-emerald-600 font-medium"}>
                {changeJustification.trim().length} / 20 chars min
              </span>
            </div>
          </div>

          {activateError && <InlineError message={activateError} />}

          <div className="flex justify-end gap-2 pt-3 border-t border-rule">
            <Button variant="secondary" size="sm" onClick={() => setActivateModalOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={isActivating}
              disabled={changeJustification.trim().length < 20}
              onClick={handleActivate}
            >
              <Rocket className="size-3.5 mr-1" /> Confirm & Activate
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
