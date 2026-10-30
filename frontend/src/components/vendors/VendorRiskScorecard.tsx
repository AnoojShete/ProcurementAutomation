import React, { useState, useEffect, useMemo } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  AlertOctagon,
  CheckCircle2,
  RefreshCw,
  Download,
  Printer,
  ChevronDown,
  ChevronRight,
  Sliders,
  FileText,
  History,
  Lock,
  Scale,
  Upload,
  Play,
  Info,
  ExternalLink,
  Check,
  Clock,
  Building,
  UserCheck,
  Briefcase,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { vendorsApi } from "@/api/vendors";
import type {
  ScorecardExplanation,
  ScorecardRuleResult,
  RemediationPlan,
  WhatIfResult,
  RiskHistoryEntry,
  VendorDispute,
  VendorEvidence,
} from "@/types/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatDate, formatDateTime } from "@/lib/format";

interface VendorRiskScorecardProps {
  vendorId: string;
  vendorName?: string;
  vendorTier?: string;
}


const EVIDENCE_TYPES: { value: string; label: string }[] = [
  { value: "financial_statement", label: "Audited financial statements" },
  { value: "credit_rating", label: "Credit rating" },
  { value: "gst_certificate", label: "GST registration certificate" },
  { value: "certificate_of_incorporation", label: "Certificate of incorporation" },
  { value: "iso27001", label: "ISO 27001 certificate" },
  { value: "soc2", label: "SOC 2 report" },
];
const evidenceLabel = (t: string) => EVIDENCE_TYPES.find((e) => e.value === t)?.label ?? t;

// The evidence type that answers each scorecard signal.
const EVIDENCE_FOR_SIGNAL: Record<string, string> = {
  financial: "financial_statement",
  gst: "gst_certificate",
  company_age: "certificate_of_incorporation",
  certification: "iso27001",
};

// Audited statement figures finance copies from the filing (one unit for all).
const STATEMENT_FIGURES: { key: string; label: string }[] = [
  { key: "total_equity", label: "Total equity" },
  { key: "profit_after_tax", label: "Profit after tax" },
  { key: "current_assets", label: "Total current assets" },
  { key: "current_liabilities", label: "Total current liabilities" },
  { key: "total_borrowings", label: "Total borrowings" },
];

type EvidenceForm = {
  evidence_type: string;
  title: string;
  valid_from: string;
  valid_until: string;
  source: string;
  agency: string;
  grade: string;
  figures: Record<string, string>;
  unit: string;
  audit_opinion: string;
  going_concern_doubt: boolean;
};

const emptyEvidence = (evidence_type = "financial_statement"): EvidenceForm => ({
  evidence_type, title: "", valid_from: "", valid_until: "", source: "", agency: "", grade: "",
  figures: {}, unit: "Rs crore", audit_opinion: "unmodified", going_concern_doubt: false,
});

const fieldClass = "w-full text-sm p-2 border border-rule rounded bg-sheet text-ink";

export function VendorRiskScorecard({ vendorId, vendorName, vendorTier }: VendorRiskScorecardProps) {
  const { user } = useAuth();

  // Tab State
  const [viewTab, setViewTab] = useState<"scorecard" | "remediation" | "history" | "evidence" | "audit" | "disputes">("scorecard");

  // Core Scorecard Data
  const [explanation, setExplanation] = useState<ScorecardExplanation | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRecomputing, setIsRecomputing] = useState(false);

  // Expanded Table Rows
  const [expandedRows, setExpandedRows] = useState<Record<string, boolean>>({});

  // Remediation & What-If
  const [remediationPlan, setRemediationPlan] = useState<RemediationPlan | null>(null);
  const [simulatedRules, setSimulatedRules] = useState<string[]>([]);
  const [whatIfResult, setWhatIfResult] = useState<WhatIfResult | null>(null);
  const [isSimulating, setIsSimulating] = useState(false);

  // History & Deltas
  const [history, setHistory] = useState<RiskHistoryEntry[]>([]);

  // Evidence
  const [evidenceList, setEvidenceList] = useState<VendorEvidence[]>([]);
  const [uploadEvidenceModal, setUploadEvidenceModal] = useState(false);
  const [evidenceForm, setEvidenceForm] = useState<EvidenceForm>(emptyEvidence());
  const [isUploadingEvidence, setIsUploadingEvidence] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);

  // Replay & Audit
  const [replayResult, setReplayResult] = useState<{ match: boolean; replayed_score: any } | null>(null);
  const [isReplaying, setIsReplaying] = useState(false);

  // Disputes
  const [disputesList, setDisputesList] = useState<VendorDispute[]>([]);
  const [disputeModalOpen, setDisputeModalOpen] = useState(false);
  const [disputeRuleResult, setDisputeRuleResult] = useState<ScorecardRuleResult | null>(null);
  const [disputeReason, setDisputeReason] = useState("");
  const [isSubmittingDispute, setIsSubmittingDispute] = useState(false);
  const [disputeSuccess, setDisputeSuccess] = useState<string | null>(null);

  const loadAllData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [expRes, remRes, histRes, eviRes, dispRes] = await Promise.allSettled([
        vendorsApi.explanation(vendorId),
        vendorsApi.remediationPlan(vendorId, "internal"),
        vendorsApi.history(vendorId),
        vendorsApi.evidence(vendorId),
        vendorsApi.disputes(vendorId),
      ]);

      if (expRes.status === "fulfilled") {
        setExplanation(expRes.value.data);
      } else {
        throw new Error(expRes.reason?.message || "Failed to load risk scorecard explanation");
      }

      if (remRes.status === "fulfilled") {
        setRemediationPlan(remRes.value.data);
      }
      if (histRes.status === "fulfilled") {
        setHistory(histRes.value.data || []);
      }
      if (eviRes.status === "fulfilled") {
        setEvidenceList(eviRes.value.data || []);
      }
      if (dispRes.status === "fulfilled") {
        setDisputesList(dispRes.value.data || []);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load risk scorecard");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAllData();
  }, [vendorId]);

  const toggleRow = (ruleId: string) => {
    setExpandedRows((prev) => ({ ...prev, [ruleId]: !prev[ruleId] }));
  };

  const handleRecompute = async (refreshSignals = false) => {
    setIsRecomputing(true);
    try {
      await vendorsApi.recomputeRisk(vendorId);
      await loadAllData();
    } catch (err: any) {
      setError(err?.message || "Recompute failed");
    } finally {
      setIsRecomputing(false);
    }
  };

  const handleSimulateRuleToggle = async (ruleId: string) => {
    const updated = simulatedRules.includes(ruleId)
      ? simulatedRules.filter((r) => r !== ruleId)
      : [...simulatedRules, ruleId];
    setSimulatedRules(updated);

    if (updated.length === 0) {
      setWhatIfResult(null);
      return;
    }

    setIsSimulating(true);
    try {
      const res = await vendorsApi.whatIf(vendorId, updated);
      setWhatIfResult(res.data);
    } catch (err) {
      console.error("What-if simulation error", err);
    } finally {
      setIsSimulating(false);
    }
  };

  const handleReplayRating = async () => {
    setIsReplaying(true);
    setReplayResult(null);
    try {
      const res = await vendorsApi.replay(vendorId, explanation?.score_id);
      setReplayResult(res.data);
    } catch (err: any) {
      setError(err?.message || "Replay failed");
    } finally {
      setIsReplaying(false);
    }
  };

  const handleExportJson = () => {
    if (!explanation) return;
    const blob = new Blob([JSON.stringify(explanation, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `vendor-risk-scorecard-${vendorId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadVendorSafePlan = async () => {
    try {
      const res = await vendorsApi.remediationPlan(vendorId, "vendor");
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `vendor-safe-remediation-${vendorId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || "Failed to download vendor-safe plan");
    }
  };

  const handleSubmitDispute = async () => {
    if (!disputeRuleResult || !disputeReason.trim()) return;
    setIsSubmittingDispute(true);
    try {
      const res = await vendorsApi.raiseDispute(vendorId, {
        rule_result_id: disputeRuleResult.rule_id,
        reason: disputeReason.trim(),
      });
      setDisputesList((prev) => [res.data, ...prev]);
      setDisputeModalOpen(false);
      setDisputeReason("");
      setDisputeRuleResult(null);
      setDisputeSuccess("Assessment dispute submitted for compliance review.");
    } catch (err: any) {
      setError(err?.message || "Failed to submit dispute");
    } finally {
      setIsSubmittingDispute(false);
    }
  };

  const openEvidence = (evidenceType?: string) => {
    setEvidenceForm(emptyEvidence(evidenceType));
    setUploadEvidenceModal(true);
  };

  const isStatement = evidenceForm.evidence_type === "financial_statement";
  const statementComplete = STATEMENT_FIGURES.every((f) => evidenceForm.figures[f.key]?.trim());
  const canSaveEvidence =
    evidenceForm.title.trim() !== "" &&
    (!isStatement || (statementComplete && evidenceForm.valid_from !== "")) &&
    (evidenceForm.evidence_type !== "credit_rating" || evidenceForm.grade.trim() !== "");

  const handleUploadEvidence = async () => {
    const f = evidenceForm;
    let metadata: Record<string, unknown> = {};
    if (isStatement) {
      metadata = {
        ...Object.fromEntries(STATEMENT_FIGURES.map(({ key }) => [key, Number(f.figures[key])])),
        unit: f.unit,
        period_end: f.valid_from,
        audit_opinion: f.audit_opinion,
        going_concern_doubt: f.going_concern_doubt,
      };
    } else if (f.evidence_type === "credit_rating") {
      metadata = { agency: f.agency.trim() || "CRISIL", grade: f.grade.trim().toUpperCase() };
    }
    if (f.source.trim()) metadata.source = f.source.trim();
    setIsUploadingEvidence(true);
    setUploadSuccess(null);
    try {
      await vendorsApi.addEvidence(vendorId, {
        evidence_type: f.evidence_type,
        title: f.title.trim(),
        valid_from: f.valid_from || undefined,
        valid_until: f.valid_until || undefined,
        notes: f.source.trim() || undefined,
        metadata,
      });
      const list = await vendorsApi.evidence(vendorId);
      setEvidenceList(list.data || []);
      setUploadEvidenceModal(false);
      setUploadSuccess("Evidence recorded. The risk score was recalculated with it.");
      await handleRecompute(true);
    } catch (err: any) {
      setError(err?.message || "Failed to record evidence");
    } finally {
      setIsUploadingEvidence(false);
    }
  };

  // --- Hooks must all be declared before any conditional return (React Rules of Hooks) ---
  // Normalize breakdown rows across both score_breakdown and legacy signals payloads
  const rawBreakdownList = explanation?.score_breakdown || (explanation as any)?.signals || [];
  const scoreBreakdown: ScorecardRuleResult[] = useMemo(() => {
    return rawBreakdownList.map((r: any) => ({
      ...r,
      signal_label: r.signal_label || r.label || r.signal_key,
      group_key: r.group_key || r.group || "",
      potential_points: r.potential_points ?? r.max_points ?? r.points ?? 0,
      override_band: r.override_band || null,
    }));
  }, [rawBreakdownList]);

  const totalPoints = explanation?.total_points ?? 0;
  const computedSum = useMemo(() => {
    return scoreBreakdown.reduce((acc, r) => acc + (r.points || 0), 0);
  }, [scoreBreakdown]);
  const isSumValid = totalPoints === computedSum;

  const unassessedList = useMemo(() => {
    if (!explanation) return [];
    if (explanation.unassessed_signals && explanation.unassessed_signals.length > 0) {
      return explanation.unassessed_signals;
    }
    return scoreBreakdown
      .filter((r) => r.status === "not_assessed")
      .map((r) => ({
        signal_key: r.signal_key,
        signal_label: r.signal_label || r.signal_key,
        potential_points: r.potential_points || 0,
        provider: (r.facts?.find((f) => f.label === "Source")?.value) || "External registry",
        reason_not_assessed: r.reason_text || "No observation available",
      }));
  }, [explanation, scoreBreakdown]);

  const overrideDetails = useMemo(() => {
    if (!explanation) return [];
    if (explanation.override_details && explanation.override_details.length > 0) {
      return explanation.override_details;
    }
    return scoreBreakdown
      .filter((r) => !!r.override_band)
      .map((r) => ({
        rule_id: r.rule_id,
        signal_key: r.signal_key,
        override_band: r.override_band!,
        rationale: r.rationale || r.reason_text,
      }));
  }, [explanation, scoreBreakdown]);

  const provisionalMessages = useMemo(() => {
    if (!explanation) return [];
    return (explanation.provisional_reasons || []).map((r: any) =>
      typeof r === "string" ? r : r?.message || r?.code || JSON.stringify(r)
    );
  }, [explanation]);

  const remediationActions = useMemo(() => {
    if (!remediationPlan) return [];
    if (remediationPlan.actions && remediationPlan.actions.length > 0) {
      return remediationPlan.actions;
    }
    if ((remediationPlan as any).items) {
      return (remediationPlan as any).items.map((it: any) => ({
        rule_id: it.rule_id,
        step: it.action || it.signal_label,
        points: it.points_recoverable ?? it.current_points ?? 0,
        evidence: it.action || "Supporting documentation",
        who: it.raw_actions?.[0]?.who || "vendor",
      }));
    }
    return [];
  }, [remediationPlan]);

  const recoverablePoints = useMemo(() => {
    if (remediationPlan?.recoverable_points != null) return remediationPlan.recoverable_points;
    const plan = remediationPlan as any;
    if (plan?.current_total != null && plan?.new_total_if_all_done != null) {
      return Math.max(0, plan.current_total - plan.new_total_if_all_done);
    }
    return 0;
  }, [remediationPlan]);

  if (loading && !explanation) {
    return (
      <div className="flex h-64 items-center justify-center">
        <div className="size-6 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      </div>
    );
  }

  if (error && !explanation) {
    return <InlineError message={error} />;
  }

  if (!explanation) return null;

  const bandTone =
    explanation.final_band === "High" ? "danger" : explanation.final_band === "Medium" ? "warning"
      : explanation.final_band === "Low" ? "success" : "neutral";
  // The API nests these under audit / range; older payloads had them at the top level.
  const audit = ((explanation as any).audit ?? {}) as Record<string, any>;
  const range = ((explanation as any).range ?? {}) as Record<string, any>;
  const assessedAt = explanation.assessed_at ?? audit.assessed_at;
  const rulesetVersion = explanation.ruleset_version ?? audit.ruleset_version;
  const worstPoints = explanation.worst_case_points ?? range.worst_case_points ?? totalPoints;
  const worstBand = explanation.worst_case_band ?? range.worst_case_band ?? explanation.final_band;
  const unassessedPoints = explanation.unassessed_potential_points ?? range.unassessed_potential ?? 0;

  return (
    <div className="flex flex-col gap-6">
      {/* 9.1 HEADER SECTION */}
      <Card>
        <CardBody className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5">
                <h1 className="text-xl font-bold text-ink">{vendorName || "Vendor"}</h1>
                {vendorTier && <Badge tone="neutral">{vendorTier}</Badge>}
                <Badge tone={bandTone}>
                  {explanation.final_band} Risk ({totalPoints} / 100 pts)
                </Badge>
                {explanation.rating_status && (
                  <Badge
                    tone={
                      explanation.rating_status === "assessed"
                        ? "success"
                        : explanation.rating_status === "provisional"
                        ? "warning"
                        : "neutral"
                    }
                  >
                    Rating: {explanation.rating_status.replace("_", " ")}
                  </Badge>
                )}
                {explanation.is_provisional && (
                  <span title={provisionalMessages.join("; ")}><Badge tone="warning">
                    Provisional — missing required signals
                  </Badge></span>
                )}
              </div>
              <p className="mt-1 text-xs text-ink-2">
                Last assessed: {formatDateTime(assessedAt)} • Trigger:{" "}
                <span className="font-semibold text-ink uppercase text-11">
                  {(explanation as any).trigger_type || "manual"}
                </span>{" "}
                • Ruleset: <span className="font-semibold text-ink">Ruleset v{rulesetVersion}</span>
                {(explanation as any).applicable_max_points && (
                  <span> • Scored out of {(explanation as any).applicable_max_points} applicable points</span>
                )}
              </p>
              <div className="mt-1 flex items-center gap-2 text-11 text-ink-3">
                <span>Thresholds: Low ≤ 24 pts | Med ≤ 49 pts | High ≥ 50 pts</span>
                <span>•</span>
                <span>
                  Worst-Case: {worstPoints} pts ({worstBand})
                </span>
              </div>
            </div>

            {/* Quick Action Buttons */}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                loading={isRecomputing}
                onClick={() => handleRecompute(false)}
                title="Re-evaluates with cached signals"
              >
                <RefreshCw className="size-3.5 mr-1" /> Recompute Rating
              </Button>
              <Button
                variant="secondary"
                size="sm"
                loading={isRecomputing}
                onClick={() => handleRecompute(true)}
                title="Forces a refetch of all signals"
              >
                <RefreshCw className="size-3.5 mr-1 text-brand-600" /> Refresh Signals
              </Button>
              <Button variant="secondary" size="sm" onClick={handleExportJson}>
                <Download className="size-3.5 mr-1" /> Export JSON
              </Button>
              <Button variant="secondary" size="sm" onClick={() => window.print()}>
                <Printer className="size-3.5 mr-1" /> Print Scorecard
              </Button>
            </div>
          </div>

          {(explanation as any).blocked_by && (explanation as any).blocked_by.length > 0 && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg text-xs text-rose-900 flex items-start gap-2">
              <AlertOctagon className="size-4 text-rose-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Blocked by Hard Overrides:</span>
                <p className="mt-0.5">
                  The vendor is currently blocked by active overrides:{" "}
                  <span className="font-mono font-semibold">{((explanation as any).blocked_by || []).map((b: any) => typeof b === "string" ? b : b?.rule_id || JSON.stringify(b)).join(", ")}</span>.
                  Downstream procurement actions are blocked until these conditions are cleared.
                </p>
              </div>
            </div>
          )}

          {provisionalMessages.length > 0 && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900 flex items-start gap-2">
              <AlertTriangle className="size-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold">Provisional Rating Warnings:</span>
                <ul className="list-inside list-disc mt-0.5 space-y-0.5">
                  {provisionalMessages.map((msg, i) => (
                    <li key={i}>{msg}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* 9.2 OVERRIDE BANNER */}
      {overrideDetails && overrideDetails.length > 0 && (
        <div className="rounded-xl border-2 border-rose-500 bg-rose-50 p-4 text-rose-950 shadow-sm animate-pulse-subtle">
          <div className="flex items-start gap-3">
            <Lock className="size-5 text-rose-600 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-bold uppercase tracking-wider text-xs bg-rose-600 text-white px-2 py-0.5 rounded">
                  Rating Locked by Hard Override Rule
                </span>
                <span className="font-mono font-bold text-xs">
                  {overrideDetails.map((o) => o.rule_id).join(", ")}
                </span>
              </div>
              <p className="text-xs font-medium">
                {overrideDetails.map((o) => o.rationale).join(". ")}
              </p>
              <p className="text-11 text-rose-800">
                Point total ({totalPoints} pts) would otherwise place vendor in{" "}
                <strong>{explanation.points_band} Risk</strong>, but this override locks final rating to{" "}
                <strong>{explanation.final_band} Risk</strong>.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Navigation Sub-Tabs */}
      <div className="flex flex-wrap gap-1.5 border-b border-rule pb-2">
        <Button
          variant={viewTab === "scorecard" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("scorecard")}
        >
          <FileText className="size-3.5 mr-1" /> Scorecard Breakdown
        </Button>
        <Button
          variant={viewTab === "remediation" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("remediation")}
        >
          <Sliders className="size-3.5 mr-1" /> Remediation & What-If ({remediationActions.length})
        </Button>
        <Button
          variant={viewTab === "history" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("history")}
        >
          <History className="size-3.5 mr-1" /> Rating History ({history.length})
        </Button>
        <Button
          variant={viewTab === "evidence" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("evidence")}
        >
          <Upload className="size-3.5 mr-1" /> Evidence Register ({evidenceList.length})
        </Button>
        <Button
          variant={viewTab === "audit" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("audit")}
        >
          <CheckCircle2 className="size-3.5 mr-1" /> Audit & Determinism
        </Button>
        <Button
          variant={viewTab === "disputes" ? "primary" : "secondary"}
          size="sm"
          onClick={() => setViewTab("disputes")}
        >
          <Scale className="size-3.5 mr-1" /> Disputes ({disputesList.length})
        </Button>
      </div>

      {disputeSuccess && <InlineSuccess message={disputeSuccess} />}
      {uploadSuccess && <InlineSuccess message={uploadSuccess} />}

      {/* TAB 1: SCORECARD BREAKDOWN & NARRATIVE */}
      {viewTab === "scorecard" && (
        <div className="flex flex-col gap-6">
          {/* 9.3 THOUGHT PROCESS CARDS */}
          {explanation.thought_process && explanation.thought_process.length > 0 && (
            <Card>
              <CardHeader
                title="Assessment Narrative"
                subtitle="Step-by-step audit rationale generated from ruleset templates"
              />
              <CardBody className="space-y-3">
                {explanation.thought_process.map((step, idx) => {
                  const icons = [
                    <Building key="1" className="size-4 text-brand-600" />,
                    <ShieldAlert key="2" className="size-4 text-amber-600" />,
                    <Briefcase key="3" className="size-4 text-indigo-600" />,
                    <UserCheck key="4" className="size-4 text-emerald-600" />,
                  ];
                  return (
                    <div key={idx} className="flex items-start gap-3 p-3 bg-sheet-subtle rounded-lg border border-rule">
                      <div className="mt-0.5">{icons[idx % icons.length]}</div>
                      {typeof step === "string" ? (
                        <p className="text-13 text-ink leading-relaxed">{step}</p>
                      ) : (
                        <p className="text-13 text-ink leading-relaxed">
                          {step.group_label && <span className="font-medium">{step.group_label}</span>}
                          {step.points != null && step.max_points != null && (
                            <span className="text-ink-3"> · {step.points} / {step.max_points} pts</span>
                          )}
                          {step.narrative && <span className="block">{step.narrative}</span>}
                        </p>
                      )}
                    </div>
                  );
                })}
              </CardBody>
            </Card>
          )}

          {/* 9.4 SCORE BREAKDOWN TABLE */}
          <Card>
            <CardHeader
              title="Signal Evaluation & Score Breakdown"
              subtitle="Sum of integer points across all signals exactly equals total points"
            />
            <CardBody className="p-0">
              <div className="overflow-x-auto">
                <table className="min-w-full text-xs text-left divide-y divide-rule">
                  <thead className="bg-sheet-subtle text-ink-2 font-medium">
                    <tr>
                      <th className="px-4 py-2.5">Signal</th>
                      <th className="px-4 py-2.5">Observed Value</th>
                      <th className="px-4 py-2.5">Status</th>
                      <th className="px-4 py-2.5">Points</th>
                      <th className="px-4 py-2.5">Reason Text</th>
                      <th className="px-4 py-2.5 text-right">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {(scoreBreakdown || []).map((row) => {
                      const isExpanded = !!expandedRows[row.rule_id];
                      return (
                        <React.Fragment key={row.rule_id}>
                          <tr className="hover:bg-sheet-subtle/50 transition-colors">
                            <td className="px-4 py-3 font-medium text-ink">
                              {row.signal_label || row.signal_key}
                              <div className="text-caption text-ink-3 uppercase">{row.group_key}</div>
                            </td>
                            <td className="px-4 py-3 font-mono text-ink-2">
                              {/* Render formatted value or primary fact */}
                              {row.facts?.[0]?.value || (row.status === "not_assessed" ? "—" : "Observed")}
                            </td>
                            <td className="px-4 py-3">
                              <Badge
                                tone={
                                  row.status === "assessed"
                                    ? row.points > 0
                                      ? "warning"
                                      : "success"
                                    : row.status === "not_assessed"
                                    ? "neutral"
                                    : "brand"
                                }
                              >
                                {row.status.replace("_", " ")}
                              </Badge>
                            </td>
                            <td className="px-4 py-3 font-semibold text-ink tabular-nums">
                              {row.points} / {row.potential_points || row.points}
                            </td>
                            <td className="px-4 py-3 text-ink-2 max-w-md">{row.reason_text}</td>
                            <td className="px-4 py-3 text-right">
                              <button
                                type="button"
                                onClick={() => toggleRow(row.rule_id)}
                                className="inline-flex items-center gap-1 text-brand-600 hover:text-brand-800 text-xs font-medium"
                              >
                                {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                                Facts
                              </button>
                            </td>
                          </tr>

                          {/* Expandable Facts & Rationale Drawer */}
                          {isExpanded && (
                            <tr className="bg-sheet-subtle/70">
                              <td colSpan={6} className="px-6 py-3 border-t border-rule/50">
                                <div className="space-y-3">
                                  <div className="flex flex-wrap items-center justify-between gap-2">
                                    <div className="flex items-center gap-3">
                                      <span className="font-mono font-bold text-ink">Rule ID: {row.rule_id}</span>
                                      {row.override_band && (
                                        <Badge tone="danger">Hard Override: {row.override_band}</Badge>
                                      )}
                                      {row.remediable && (
                                        <Badge tone="success">Remediable by Vendor/Buyer</Badge>
                                      )}
                                      {row.ages_out_on && (
                                        <span className="text-11 text-ink-3">Ages out on: {row.ages_out_on}</span>
                                      )}
                                    </div>
                                    <Button
                                      variant="secondary"
                                      size="sm"
                                      onClick={() => {
                                        setDisputeRuleResult(row);
                                        setDisputeModalOpen(true);
                                      }}
                                    >
                                      <Scale className="size-3 mr-1" /> Raise Assessment Dispute
                                    </Button>
                                  </div>

                                  <div className="text-xs">
                                    <span className="font-semibold text-ink-2">Expert Rationale:</span>
                                    <p className="italic text-ink-1 mt-0.5">{row.rationale}</p>
                                  </div>

                                  {row.facts && row.facts.length > 0 && (
                                    <div className="border border-rule rounded-md overflow-hidden bg-sheet">
                                      <table className="min-w-full text-11 text-left divide-y divide-rule">
                                        <thead className="bg-sheet-subtle text-ink-3 font-semibold uppercase">
                                          <tr>
                                            <th className="px-3 py-1.5">Fact Field</th>
                                            <th className="px-3 py-1.5">Observed Fact Value</th>
                                          </tr>
                                        </thead>
                                        <tbody className="divide-y divide-rule">
                                          {row.facts.map((f, i) => (
                                            <tr key={i}>
                                              <td className="px-3 py-1.5 font-medium text-ink-2">{f.label}</td>
                                              <td className="px-3 py-1.5 font-mono text-ink">{f.value}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>

                  {/* Bottom Row: Sum Invariant Proof */}
                  <tfoot className="bg-slate-50 border-t-2 border-slate-300 font-semibold text-xs">
                    <tr>
                      <td colSpan={3} className="px-4 py-3 text-slate-800">
                        Total Points Identity: Σ(Rule Points) = Total Points
                      </td>
                      <td className="px-4 py-3 tabular-nums font-bold text-slate-900 text-sm">
                        {computedSum} / 100 pts
                      </td>
                      <td colSpan={2} className="px-4 py-3 text-emerald-700">
                        {isSumValid ? (
                          <span className="inline-flex items-center gap-1 font-medium">
                            <CheckCircle2 className="size-4 text-emerald-600" />
                            Exact integer sum identity confirmed (sum == total_points == {totalPoints})
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-rose-600 font-bold">
                            <AlertTriangle className="size-4" />
                            Sum mismatch invariant failure! ({computedSum} != {totalPoints})
                          </span>
                        )}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            </CardBody>
          </Card>

          {/* 9.5 UNASSESSED SIGNALS TABLE */}
          {unassessedList && unassessedList.length > 0 && (
            <Card>
              <CardHeader
                title="Unassessed Signals & Worst-Case Scenario"
                subtitle="Signals without observations contribute 0 points, but their potential impact is bounded"
              />
              <CardBody className="space-y-4">
                <div className="p-3 bg-amber-50/70 border border-amber-200 rounded-lg text-xs flex justify-between items-center">
                  <div>
                    <span className="font-semibold text-amber-900">Worst-Case Potential Score:</span>
                    <p className="text-amber-800 mt-0.5">
                      If all {unassessedList.length} unassessed signals returned their worst possible
                      value, this vendor would score{" "}
                      <strong>{worstPoints} pts ({worstBand} Risk)</strong>.
                    </p>
                  </div>
                  <Badge tone="warning">+{unassessedPoints} unassessed pts</Badge>
                </div>

                <div className="overflow-x-auto border border-rule rounded-lg">
                  <table className="min-w-full text-xs text-left divide-y divide-rule">
                    <thead className="bg-sheet-subtle text-ink-2 font-medium">
                      <tr>
                        <th className="px-4 py-2">Signal</th>
                        <th className="px-4 py-2">Provider</th>
                        <th className="px-4 py-2">Reason Not Assessed</th>
                        <th className="px-4 py-2">Max Potential Points</th>
                        <th className="px-4 py-2 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-rule">
                      {unassessedList.map((sig) => (
                        <tr key={sig.signal_key}>
                          <td className="px-4 py-2.5 font-medium text-ink">{sig.signal_label || sig.signal_key}</td>
                          <td className="px-4 py-2.5 text-ink-2">{sig.provider || "External registry"}</td>
                          <td className="px-4 py-2.5 text-ink-2">{sig.reason_not_assessed || "No observation available"}</td>
                          <td className="px-4 py-2.5 font-semibold text-ink tabular-nums">+{sig.potential_points} pts</td>
                          <td className="px-4 py-2.5 text-right">
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                openEvidence(EVIDENCE_FOR_SIGNAL[sig.signal_key]);
                              }}
                            >
                              <Upload className="size-3 mr-1" /> Upload Evidence
                            </Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      )}

      {/* TAB 2: REMEDIATION & WHAT-IF SIMULATOR */}
      {viewTab === "remediation" && (
        <div className="flex flex-col gap-6">
          {/* 9.7 WHAT-IF SIMULATOR */}
          <Card>
            <CardHeader
              title="Interactive What-If Scorecard Simulator"
              subtitle="Preview score improvements if remediable risk factors are cleared"
            />
            <CardBody className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 p-4 bg-sheet-subtle rounded-xl border border-rule">
                <div>
                  <span className="text-caption text-ink-3">Current Score</span>
                  <p className="text-lg font-bold text-ink mt-0.5">
                    {totalPoints} pts ({explanation.final_band})
                  </p>
                </div>
                <div>
                  <span className="text-caption text-ink-3">Simulated Score</span>
                  <p className="text-lg font-bold text-brand-600 mt-0.5">
                    {whatIfResult ? `${whatIfResult.simulated_points} pts (${whatIfResult.simulated_band})` : "Toggle remediations below"}
                  </p>
                </div>
                <div>
                  <span className="text-caption text-ink-3">Points Recoverable</span>
                  <p className="text-lg font-bold text-emerald-600 mt-0.5">
                    {whatIfResult ? `-${whatIfResult.score_difference} points recovered` : `${recoverablePoints} pts max`}
                  </p>
                </div>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-ink mb-2">Simulate Resolving Specific Risk Factors:</h4>
                <div className="space-y-2">
                  {remediationActions.map((step: any) => {
                    const isChecked = simulatedRules.includes(step.rule_id);
                    return (
                      <label
                        key={step.rule_id}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                          isChecked ? "bg-emerald-50/70 border-emerald-300" : "bg-sheet border-rule hover:border-slate-300"
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="mt-0.5 rounded text-brand-600 focus:ring-brand-500"
                          checked={isChecked}
                          onChange={() => handleSimulateRuleToggle(step.rule_id)}
                        />
                        <div className="flex-1 text-xs">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-ink">{step.step}</span>
                            <Badge tone="success">Save {step.points} pts</Badge>
                          </div>
                          <p className="text-ink-2 mt-0.5">Evidence: {step.evidence}</p>
                          <span className="text-11 text-ink-3 uppercase font-mono">Rule: {step.rule_id} • Assigned: {step.who}</span>
                        </div>
                      </label>
                    );
                  })}
                  {remediationActions.length === 0 && (
                    <p className="text-xs text-ink-3 py-4 text-center">No remediable penalty rules currently active.</p>
                  )}
                </div>
              </div>
            </CardBody>
          </Card>

          {/* 9.6 REMEDIATION ACTION PLAN */}
          <Card>
            <CardHeader
              title="Cumulative Remediation Path"
              subtitle={remediationPlan?.summary || "Concrete steps to lower risk score and clear active overrides"}
              action={
                <Button variant="secondary" size="sm" onClick={handleDownloadVendorSafePlan}>
                  <Download className="size-3.5 mr-1" /> Export Vendor-Safe Plan (PDF/JSON)
                </Button>
              }
            />
            <CardBody>
              <div className="overflow-x-auto border border-rule rounded-lg">
                <table className="min-w-full text-xs text-left divide-y divide-rule">
                  <thead className="bg-sheet-subtle text-ink-2 font-medium">
                    <tr>
                      <th className="px-4 py-2.5">Step</th>
                      <th className="px-4 py-2.5">Signal</th>
                      <th className="px-4 py-2.5">Action Required</th>
                      <th className="px-4 py-2.5">Points Impact</th>
                      <th className="px-4 py-2.5">Projected Band</th>
                      <th className="px-4 py-2.5">Blocked By</th>
                      <th className="px-4 py-2.5">Clearance</th>
                      <th className="px-4 py-2.5 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rule">
                    {((remediationPlan as any)?.steps || []).map((step: any, idx: number) => (
                      <tr key={idx} className="hover:bg-sheet-subtle/50">
                        <td className="px-4 py-3 font-semibold text-ink font-mono">#{step.step}</td>
                        <td className="px-4 py-3 font-medium text-ink whitespace-nowrap">{step.signal_label}</td>
                        <td className="px-4 py-3 text-ink-2 max-w-sm">{step.action}</td>
                        <td className="px-4 py-3 font-semibold tabular-nums text-emerald-600 whitespace-nowrap">
                          {step.points_before} → {step.points_after} pts (-{step.points_recoverable})
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="font-semibold">{step.band_before}</span> →{" "}
                          <span className="font-semibold text-brand-600">{step.band_after}</span>
                        </td>
                        <td className="px-4 py-3 text-ink-3 font-mono text-11">
                          {step.blocked_by && step.blocked_by.length > 0 ? (
                            <span className="text-rose-600 font-semibold">{step.blocked_by.join(", ")}</span>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          {step.would_be_cleared ? (
                            <Badge tone="success">Cleared</Badge>
                          ) : (
                            <Badge tone="neutral">Blocked</Badge>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          {step.remediable ? (
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                openEvidence(EVIDENCE_FOR_SIGNAL[step.signal_key]);
                              }}
                            >
                              <Upload className="size-3 mr-1" /> Upload
                            </Button>
                          ) : (
                            <span className="text-11 text-ink-3">Non-remediable</span>
                          )}
                        </td>
                      </tr>
                    ))}
                    {(!((remediationPlan as any)?.steps) || (remediationPlan as any).steps.length === 0) && (
                      <tr>
                        <td colSpan={8} className="px-4 py-6 text-center text-ink-3">
                          No active remediation steps required. Vendor meets safe baseline.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* TAB 3: RATING HISTORY & DELTAS */}
      {viewTab === "history" && (
        <Card>
          <CardHeader
            title="Rating Assessment History"
            subtitle="Immutable record of all historical deterministic scorecard assessments"
          />
          <CardBody>
            <div className="overflow-x-auto border border-rule rounded-lg">
              <table className="min-w-full text-xs text-left divide-y divide-rule">
                <thead className="bg-sheet-subtle text-ink-2 font-medium">
                  <tr>
                    <th className="px-4 py-2.5">Assessed At</th>
                    <th className="px-4 py-2.5">Score</th>
                    <th className="px-4 py-2.5">Risk Band</th>
                    <th className="px-4 py-2.5">Provisional</th>
                    <th className="px-4 py-2.5">Trigger Type</th>
                    <th className="px-4 py-2.5">Ruleset</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {history.map((h) => (
                    <tr key={h.id} className="hover:bg-sheet-subtle/50">
                      <td className="px-4 py-2.5 font-medium text-ink">{formatDateTime(h.assessed_at)}</td>
                      <td className="px-4 py-2.5 font-bold text-ink tabular-nums">{h.total_points} pts</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={h.final_band === "High" ? "danger" : h.final_band === "Medium" ? "warning" : "success"}>
                          {h.final_band}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5">
                        {h.is_provisional ? <span className="text-amber-600 font-medium">Yes</span> : "No"}
                      </td>
                      <td className="px-4 py-2.5 uppercase text-11 text-ink-2">{h.trigger_type}</td>
                      <td className="px-4 py-2.5 text-ink-2 font-mono">v{h.ruleset_version}</td>
                    </tr>
                  ))}
                  {history.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-ink-3">No previous history entries.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {/* TAB 4: EVIDENCE REGISTER */}
      {viewTab === "evidence" && (
        <Card>
          <CardHeader
            title="Evidence Register"
            subtitle="Authoritative supplier compliance documents and verification certificates"
            action={
              <Button variant="primary" size="sm" onClick={() => openEvidence()}>
                <Upload className="size-3.5 mr-1" /> Add evidence
              </Button>
            }
          />
          <CardBody>
            <div className="overflow-x-auto border border-rule rounded-lg">
              <table className="min-w-full text-xs text-left divide-y divide-rule">
                <thead className="bg-sheet-subtle text-ink-2 font-medium">
                  <tr>
                    <th className="px-4 py-2.5">Type</th>
                    <th className="px-4 py-2.5">Title</th>
                    <th className="px-4 py-2.5">Valid From</th>
                    <th className="px-4 py-2.5">Valid Until</th>
                    <th className="px-4 py-2.5">Verification</th>
                    <th className="px-4 py-2.5">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {evidenceList.map((e) => (
                    <tr key={e.id} className="hover:bg-sheet-subtle/50">
                      <td className="px-4 py-2.5 font-medium text-ink">{evidenceLabel(e.evidence_type)}</td>
                      <td className="px-4 py-2.5 text-ink-2">{e.title}</td>
                      <td className="px-4 py-2.5 text-ink-2">{e.valid_from ? formatDate(e.valid_from) : "—"}</td>
                      <td className="px-4 py-2.5 text-ink-2">{e.valid_until ? formatDate(e.valid_until) : "Ongoing"}</td>
                      <td className="px-4 py-2.5 text-ink-2">{e.verified_by || "Pending review"}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={e.status === "accepted" ? "success" : e.status === "rejected" ? "danger" : "neutral"}>
                          {e.status === "accepted" ? "Accepted" : e.status === "pending_review" ? "Pending review" : e.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                  {evidenceList.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-ink-3">No evidence recorded yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {/* TAB 5: AUDIT TAB */}
      {viewTab === "audit" && (
        <Card>
          <CardHeader
            title="Cryptographic Traceability & Byte-Identical Replay"
            subtitle="100% deterministic score invariant verification"
            action={
              <a
                href={`/api/vendors/${vendorId}/risk/audit-bundle?score_id=${explanation.score_id}`}
                download
                className="inline-flex items-center gap-1.5 rounded-lg border border-rule bg-sheet px-3 py-1.5 text-xs font-medium text-ink hover:bg-sheet-subtle"
              >
                <Download className="size-3.5" /> Download Full Audit Bundle (ZIP)
              </a>
            }
          />
          <CardBody className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="p-4 bg-sheet-subtle rounded-lg border border-rule">
                <span className="text-caption text-ink-3">Snapshot SHA-256 Hash</span>
                <p className="font-mono text-xs text-ink font-semibold mt-1 break-all">
                  {explanation.snapshot_sha256}
                </p>
                <p className="text-11 text-ink-3 mt-1">Canonical SHA-256 hash of all 14 signal observations evaluated.</p>
              </div>
              <div className="p-4 bg-sheet-subtle rounded-lg border border-rule">
                <span className="text-caption text-ink-3">Assessment ID</span>
                <p className="font-mono text-xs text-ink font-semibold mt-1 break-all">{explanation.score_id}</p>
                <p className="text-11 text-ink-3 mt-1">Immutable primary key in risk_scores append-only log.</p>
              </div>
            </div>

            <div className="p-4 border border-rule rounded-lg space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-xs font-semibold text-ink">Replay Assessment Determinism Test</h4>
                  <p className="text-11 text-ink-2">
                    Fetches the exact snapshot and ruleset v{rulesetVersion} used and asserts byte-identical output.
                  </p>
                </div>
                <Button variant="primary" size="sm" loading={isReplaying} onClick={handleReplayRating}>
                  <Play className="size-3 mr-1" /> Replay Assessment
                </Button>
              </div>

              {replayResult && (
                <div
                  className={`p-3 rounded-lg border text-xs flex items-center gap-2 ${
                    replayResult.match
                      ? "bg-emerald-50 border-emerald-300 text-emerald-900"
                      : "bg-rose-50 border-rose-300 text-rose-900"
                  }`}
                >
                  <CheckCircle2 className="size-4 text-emerald-600 shrink-0" />
                  <div>
                    <span className="font-bold">200 OK — Replayed Byte-For-Byte Identical Rating!</span>
                    <p className="text-11 text-emerald-800">
                      Replay produced {replayResult.replayed_score.total_points} points ({replayResult.replayed_score.final_band} Band), matching stored score record exactly.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </CardBody>
        </Card>
      )}

      {/* TAB 6: DISPUTES WORKFLOW */}
      {viewTab === "disputes" && (
        <Card>
          <CardHeader
            title="Vendor Assessment Disputes"
            subtitle="Four-eyes governance workflow for supplier risk disputes"
          />
          <CardBody>
            <div className="overflow-x-auto border border-rule rounded-lg">
              <table className="min-w-full text-xs text-left divide-y divide-rule">
                <thead className="bg-sheet-subtle text-ink-2 font-medium">
                  <tr>
                    <th className="px-4 py-2.5">Disputed Rule</th>
                    <th className="px-4 py-2.5">Raised At</th>
                    <th className="px-4 py-2.5">Raised By</th>
                    <th className="px-4 py-2.5">Reason</th>
                    <th className="px-4 py-2.5">Status</th>
                    <th className="px-4 py-2.5">Resolution Note</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {disputesList.map((d) => (
                    <tr key={d.id} className="hover:bg-sheet-subtle/50">
                      <td className="px-4 py-2.5 font-mono font-bold text-ink">{d.rule_result_id}</td>
                      <td className="px-4 py-2.5 text-ink-2">{formatDateTime(d.raised_at)}</td>
                      <td className="px-4 py-2.5 text-ink">{d.raised_by}</td>
                      <td className="px-4 py-2.5 text-ink-2 max-w-xs">{d.reason}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={d.status === "upheld" ? "success" : d.status === "rejected" ? "danger" : "warning"}>
                          {d.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 text-ink-2">{d.resolution_note || "Pending four-eyes review"}</td>
                    </tr>
                  ))}
                  {disputesList.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-4 py-6 text-center text-ink-3">No active disputes raised for this vendor.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}

      {/* DISPUTE MODAL */}
      <Modal
        open={disputeModalOpen}
        onClose={() => setDisputeModalOpen(false)}
        title={`Raise Dispute on Rule ${disputeRuleResult?.rule_id || ""}`}
        size="md"
      >
        <div className="space-y-4">
          <p className="text-xs text-ink-2">
            Disputing this outcome flags it for compliance review. Reviewer must differ from the user raising this dispute.
          </p>

          <div className="p-3 bg-sheet-subtle border border-rule rounded text-xs space-y-1">
            <p><strong>Signal:</strong> {disputeRuleResult?.signal_label || disputeRuleResult?.signal_key}</p>
            <p><strong>Assessed Points:</strong> {disputeRuleResult?.points} pts</p>
            <p><strong>Reason Text:</strong> {disputeRuleResult?.reason_text}</p>
          </div>

          <div>
            <label className="block text-xs font-semibold text-ink mb-1">
              Dispute Justification <span className="text-rose-500">*</span>
            </label>
            <textarea
              className="w-full text-xs p-2.5 border border-rule rounded bg-sheet text-ink focus:outline-none focus:ring-1 focus:ring-brand-500"
              rows={4}
              placeholder="State why this observation or rule outcome is disputed..."
              value={disputeReason}
              onChange={(e) => setDisputeReason(e.target.value)}
            />
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-rule">
            <Button variant="secondary" size="sm" onClick={() => setDisputeModalOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={isSubmittingDispute}
              disabled={!disputeReason.trim()}
              onClick={handleSubmitDispute}
            >
              Submit Dispute
            </Button>
          </div>
        </div>
      </Modal>

      {/* EVIDENCE MODAL */}
      <Modal
        open={uploadEvidenceModal}
        onClose={() => setUploadEvidenceModal(false)}
        title="Record evidence"
        size="md"
      >
        <div className="space-y-4 text-sm">
          <label className="block">
            <span className="block text-xs font-semibold text-ink mb-1">Type</span>
            <select
              className={fieldClass}
              value={evidenceForm.evidence_type}
              onChange={(e) => setEvidenceForm(emptyEvidence(e.target.value))}
            >
              {EVIDENCE_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="block text-xs font-semibold text-ink mb-1">Title</span>
            <input
              className={fieldClass}
              placeholder={isStatement ? "Audited consolidated results, FY 2025-26" : "Certificate number or name"}
              value={evidenceForm.title}
              onChange={(e) => setEvidenceForm({ ...evidenceForm, title: e.target.value })}
            />
          </label>

          {evidenceForm.evidence_type === "credit_rating" && (
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="block text-xs font-semibold text-ink mb-1">Agency</span>
                <input className={fieldClass} placeholder="CRISIL" value={evidenceForm.agency}
                  onChange={(e) => setEvidenceForm({ ...evidenceForm, agency: e.target.value })} />
              </label>
              <label className="block">
                <span className="block text-xs font-semibold text-ink mb-1">Grade</span>
                <input className={fieldClass} placeholder="AA+" value={evidenceForm.grade}
                  onChange={(e) => setEvidenceForm({ ...evidenceForm, grade: e.target.value })} />
              </label>
            </div>
          )}

          {isStatement && (
            <div className="space-y-3">
              <p className="text-xs text-ink-2">
                Copy these from the latest audited statements, all in one unit. The score is the share of five
                checks passed: positive net worth, a profit, enough liquidity, low borrowing and a clean audit.
              </p>
              <div className="grid grid-cols-2 gap-3">
                {STATEMENT_FIGURES.map((f) => (
                  <label key={f.key} className="block">
                    <span className="block text-xs font-semibold text-ink mb-1">{f.label}</span>
                    <input
                      type="number"
                      step="any"
                      className={`${fieldClass} tabular-nums`}
                      value={evidenceForm.figures[f.key] ?? ""}
                      onChange={(e) =>
                        setEvidenceForm({ ...evidenceForm, figures: { ...evidenceForm.figures, [f.key]: e.target.value } })
                      }
                    />
                  </label>
                ))}
                <label className="block">
                  <span className="block text-xs font-semibold text-ink mb-1">Unit</span>
                  <input className={fieldClass} value={evidenceForm.unit}
                    onChange={(e) => setEvidenceForm({ ...evidenceForm, unit: e.target.value })} />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="block text-xs font-semibold text-ink mb-1">Auditor's opinion</span>
                  <select className={fieldClass} value={evidenceForm.audit_opinion}
                    onChange={(e) => setEvidenceForm({ ...evidenceForm, audit_opinion: e.target.value })}>
                    <option value="unmodified">Unmodified</option>
                    <option value="qualified">Qualified</option>
                    <option value="adverse">Adverse</option>
                    <option value="disclaimer">Disclaimer</option>
                  </select>
                </label>
                <label className="flex items-end gap-2 pb-2">
                  <input type="checkbox" checked={evidenceForm.going_concern_doubt}
                    onChange={(e) => setEvidenceForm({ ...evidenceForm, going_concern_doubt: e.target.checked })} />
                  <span className="text-xs text-ink">Auditor reports a going-concern doubt</span>
                </label>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="block text-xs font-semibold text-ink mb-1">{isStatement ? "Period end" : "Valid from"}</span>
              <input type="date" className={fieldClass} value={evidenceForm.valid_from}
                onChange={(e) => setEvidenceForm({ ...evidenceForm, valid_from: e.target.value })} />
            </label>
            {!isStatement && (
              <label className="block">
                <span className="block text-xs font-semibold text-ink mb-1">Valid until</span>
                <input type="date" className={fieldClass} value={evidenceForm.valid_until}
                  onChange={(e) => setEvidenceForm({ ...evidenceForm, valid_until: e.target.value })} />
              </label>
            )}
          </div>

          <label className="block">
            <span className="block text-xs font-semibold text-ink mb-1">Source</span>
            <input className={fieldClass} placeholder="Link to the filing or certificate"
              value={evidenceForm.source}
              onChange={(e) => setEvidenceForm({ ...evidenceForm, source: e.target.value })} />
          </label>

          <div className="flex justify-end gap-2 pt-3 border-t border-rule">
            <Button variant="secondary" size="sm" onClick={() => setUploadEvidenceModal(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={isUploadingEvidence}
              disabled={!canSaveEvidence}
              onClick={handleUploadEvidence}
            >
              Save and re-score
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
