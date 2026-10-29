import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  Building2,
  CheckCircle2,
  FileText,
  Info,
  Layers,
  Lock,
  Search,
  ShoppingCart,
  Sparkles,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useAuth } from "@/hooks/useAuth";
import { useApi } from "@/hooks/useApi";
import { useDebounce } from "@/hooks/useDebounce";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { documentsApi } from "@/api/documents";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { NumberedStepper } from "@/components/ui/NumberedStepper";
import { FileUploader } from "@/components/ui/FileUploader";
import { LifecycleStepper } from "@/components/ui/LifecycleStepper";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { RiskBadge } from "@/components/ui/Badge";
import { formatCurrency, titleCase } from "@/lib/format";
import { SPEND_TIERS, SLA_APPROVAL_TIMEOUT_HOURS } from "@/lib/constants";
import { deriveUploadPipeline, deriveMultiUploadPipeline } from "@/lib/documentPipeline";
import { DocumentPreviewCard } from "@/components/documents/DocumentPreviewCard";
import type { CreatePurchaseRequestBody, DocumentRecord, RequestType, VendorSummary } from "@/types/api";
import { ApiError } from "@/api/client";

const STEPS = ["Details", "Vendor", "Documents", "Review", "Submit"];

export interface RequestDraft {
  id: string; // document id
  document: DocumentRecord;
  requestType: RequestType;
  department: string;
  amount: string;
  description: string;
  vendorId: string | null;
  vendor: VendorSummary | null;
}

interface WizardState {
  requestType: RequestType;
  department: string;
  amount: string;
  description: string;
  vendorId: string | null;
  vendor: VendorSummary | null;
  document: DocumentRecord | null;
  drafts: RequestDraft[];
}

function parseAmount(val: unknown): number | null {
  if (val == null) return null;
  if (typeof val === "number") return isNaN(val) ? null : val;
  if (typeof val === "string") {
    const cleaned = val.replace(/,/g, "").trim();
    const num = Number(cleaned);
    return isNaN(num) ? null : num;
  }
  return null;
}

export function buildDraftFromDocument(
  doc: DocumentRecord,
  vendors: VendorSummary[] | null,
  defaultDept?: string,
): RequestDraft {
  const currency = String(doc.extracted_fields?.currency ?? "INR").toUpperCase();
  const rawTotal = parseAmount(doc.extracted_fields?.total);
  const fxTotal = parseAmount(doc.fx?.total_inr);
  const amountVal = fxTotal ?? (currency === "INR" || !currency ? rawTotal : null) ?? rawTotal;
  const amountStr =
    amountVal != null && amountVal > 0
      ? String(Math.round(amountVal * 100) / 100)
      : "";

  let matchedVendor: VendorSummary | null = null;
  if (doc.vendor_id && vendors) {
    matchedVendor = vendors.find((v) => v.id === doc.vendor_id) ?? null;
  } else if (doc.vendor_name_raw && vendors) {
    const raw = doc.vendor_name_raw.toLowerCase().trim();
    matchedVendor =
      vendors.find(
        (v) =>
          v.name.toLowerCase().includes(raw) ||
          raw.includes(v.name.toLowerCase()),
      ) ?? null;
  }

  const dept = (doc.extracted_fields?.department as string) || defaultDept || "General";
  const desc = doc.original_filename ? `Auto-extracted from ${doc.original_filename}` : "";

  return {
    id: doc.id,
    document: doc,
    requestType: "hardware",
    department: dept,
    amount: amountStr,
    description: desc,
    vendorId: matchedVendor?.id ?? null,
    vendor: matchedVendor,
  };
}

/** Fills the single-request state from a processed document. */
function applyDocument(s: WizardState, doc: DocumentRecord, vendors: VendorSummary[] | null): WizardState {
  const next = { ...s, document: doc };

  const currency = String(doc.extracted_fields?.currency ?? "INR").toUpperCase();
  const rawTotal = parseAmount(doc.extracted_fields?.total);
  const fxTotal = parseAmount(doc.fx?.total_inr);
  const amountVal = fxTotal ?? (currency === "INR" || !currency ? rawTotal : null) ?? rawTotal;
  if (amountVal != null && amountVal > 0 && (!s.amount || s.amount === "0")) {
    next.amount = String(Math.round(amountVal * 100) / 100);
  }

  if (!s.vendorId && vendors) {
    let matched: VendorSummary | undefined;
    if (doc.vendor_id) {
      matched = vendors.find((v) => v.id === doc.vendor_id);
    } else if (doc.vendor_name_raw) {
      const raw = doc.vendor_name_raw.toLowerCase().trim();
      matched = vendors.find((v) => v.name.toLowerCase().includes(raw) || raw.includes(v.name.toLowerCase()));
    }
    if (matched) {
      next.vendorId = matched.id;
      next.vendor = matched;
    }
  }

  if (!next.department.trim()) {
    next.department = (doc.extracted_fields?.department as string) || "General";
  }
  if (!next.description.trim() && doc.original_filename) {
    next.description = `Auto-extracted from ${doc.original_filename}`;
  }
  return next;
}

function resolveSpendTier(amount: number) {
  if (amount <= 500) return SPEND_TIERS[0];
  if (amount <= 5000) return SPEND_TIERS[1];
  return SPEND_TIERS[2];
}

export function NewRequestWizardPage() {
  usePageHeader("New Purchase Request", "Requests");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [state, setState] = useState<WizardState>({
    requestType: "hardware",
    department: "",
    amount: "",
    description: "",
    vendorId: null,
    vendor: null,
    document: null,
    drafts: [],
  });
  const [docProcessing, setDocProcessing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<{ id: string; status: string; tier: string } | null>(null);
  const [submittedBatch, setSubmittedBatch] = useState<
    Array<{ id: string; filename: string; amount: number; tier: string; status: string }> | null
  >(null);

  const { data: vendors, loading: vendorsLoading } = useApi(() => vendorsApi.list(200), []);

  // Started from a document ("Create a purchase request from this
  // invoice"): fill everything from it and go straight to Review.
  const [searchParams] = useSearchParams();
  const fromDocument = searchParams.get("document");
  const [prefillError, setPrefillError] = useState<string | null>(null);
  useEffect(() => {
    if (!fromDocument || vendorsLoading) return;
    documentsApi
      .get(fromDocument)
      .then((res) => {
        const draft = buildDraftFromDocument(res.data, vendors, "General");
        setState((s) => ({
          ...applyDocument(s, res.data, vendors),
          drafts: [draft],
        }));
        setStep(3);
      })
      .catch((e) => setPrefillError(e instanceof ApiError ? e.message : "Couldn't load that document."));
  }, [fromDocument, vendorsLoading]); // eslint-disable-line react-hooks/exhaustive-deps

  const amountNum = Number(state.amount) || 0;
  const tier = resolveSpendTier(amountNum);

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));
  const jumpTo = (targetStep: number) => setStep(targetStep);

  const canProceedFromReview = useMemo(() => {
    if (state.drafts.length > 1) {
      return state.drafts.every(
        (d) => (Number(d.amount) || 0) > 0 && d.department.trim().length > 0,
      );
    }
    return amountNum > 0 && state.department.trim().length > 0;
  }, [state.drafts, amountNum, state.department]);

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      if (state.drafts.length > 1) {
        const batchResults: Array<{ id: string; filename: string; amount: number; tier: string; status: string }> = [];
        for (const draft of state.drafts) {
          const draftAmount = Number(draft.amount) || 0;
          const draftTier = resolveSpendTier(draftAmount);
          const body: CreatePurchaseRequestBody = {
            request_type: draft.requestType,
            requested_by: user!.email,
            department: draft.department.trim() || "General",
            vendor_id: draft.vendorId,
            amount: draftAmount,
            currency: "INR",
            document_id: draft.document.id,
            comments: draft.description || undefined,
          };
          const res = await requestsApi.create(body);
          batchResults.push({
            id: res.data.id,
            filename: draft.document.original_filename ?? "Document",
            amount: draftAmount,
            tier: res.data.spend_tier ?? draftTier.name,
            status: res.data.status ?? "pending_approval",
          });
        }
        setSubmittedBatch(batchResults);
      } else {
        const body: CreatePurchaseRequestBody = {
          request_type: state.requestType,
          requested_by: user!.email,
          department: state.department.trim() || "General",
          vendor_id: state.vendorId,
          amount: amountNum,
          currency: "INR",
          document_id: state.document?.id ?? null,
          comments: state.description || undefined,
        };
        const res = await requestsApi.create(body);
        setSubmitted({
          id: res.data.id,
          status: res.data.status ?? "pending_approval",
          tier: res.data.spend_tier ?? tier.name,
        });
      }
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Unable to submit the request(s).");
    } finally {
      setSubmitting(false);
    }
  };

  if (submittedBatch) {
    return (
      <div className="mx-auto max-w-2xl py-8">
        <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-success-50">
          <CheckCircle2 className="size-7 text-success-600" />
        </div>
        <h1 className="text-center text-xl font-semibold text-slate-900">
          {submittedBatch.length} Independent Purchase Requests Submitted
        </h1>
        <p className="mt-2 text-center text-sm text-slate-500">
          Each uploaded document was processed and submitted as its own independent purchase request with its own approval workflow and SLA timer.
        </p>

        <div className="mt-6 divide-y divide-surface-border rounded-lg border border-surface-border bg-white shadow-sm">
          {submittedBatch.map((req, idx) => (
            <div key={req.id} className="flex items-center justify-between p-4 hover:bg-surface-subtle transition-colors">
              <div>
                <p className="font-semibold text-sm text-slate-900">
                  Request #{idx + 1}: {req.filename}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Amount: <span className="font-medium text-slate-800">{formatCurrency(req.amount)}</span> • Tier:{" "}
                  <span className="font-medium capitalize text-brand-700">{req.tier}</span> • Status:{" "}
                  <span className="font-medium text-slate-700">{titleCase(req.status)}</span>
                </p>
              </div>
              <Button size="sm" onClick={() => navigate(`/app/requests/${req.id}`)}>
                Open request
              </Button>
            </div>
          ))}
        </div>

        <div className="mt-6 flex justify-center gap-3">
          <Button variant="secondary" onClick={() => navigate("/app/requests")}>
            View all requests
          </Button>
        </div>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-lg py-12 text-center">
        <div className="mx-auto mb-4 flex size-14 items-center justify-center rounded-full bg-success-50">
          <CheckCircle2 className="size-7 text-success-600" />
        </div>
        <h1 className="text-xl font-semibold text-slate-900">Request submitted</h1>
        <p className="mt-2 text-sm text-slate-500">
          Your request is routed as <span className="font-medium capitalize">{submitted.tier}</span> tier and is now{" "}
          <span className="font-medium">{titleCase(submitted.status)}</span>.
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Button variant="secondary" onClick={() => navigate("/app/requests")}>
            View my requests
          </Button>
          <Button onClick={() => navigate(`/app/requests/${submitted.id}`)}>Open request</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <NumberedStepper steps={STEPS} currentIndex={step} />
      {prefillError && <InlineError message={prefillError} />}

      {step === 0 && <StepDetails state={state} setState={setState} onSkipToDocuments={() => jumpTo(2)} />}
      {step === 1 && (
        <StepVendor
          state={state}
          setState={setState}
          vendors={vendors}
          loading={vendorsLoading}
          onSkipToDocuments={() => jumpTo(2)}
        />
      )}
      {step === 2 && (
        <StepDocuments
          state={state}
          setState={setState}
          vendors={vendors}
          onProcessingChange={setDocProcessing}
        />
      )}
      {step === 3 && <StepReview state={state} setState={setState} amount={amountNum} tier={tier} vendors={vendors} />}
      {step === 4 && (
        <StepSubmit
          state={state}
          amount={amountNum}
          tier={tier}
          submitting={submitting}
          error={submitError}
          onSubmit={submit}
        />
      )}

      <div className="flex justify-between">
        <Button variant="secondary" onClick={back} disabled={step === 0}>
          Back
        </Button>
        {step < STEPS.length - 1 && (
          <Button
            onClick={next}
            disabled={
              (step === 2 && docProcessing) ||
              (step === 3 && !canProceedFromReview)
            }
          >
            {step === 2 && docProcessing
              ? "Extracting documents…"
              : step === 0 && (!state.department || !amountNum)
                ? "Continue"
                : step === 3
                  ? "Continue to submit"
                  : "Continue"}
          </Button>
        )}
      </div>
    </div>
  );
}

function StepDetails({
  state,
  setState,
  onSkipToDocuments,
}: {
  state: WizardState;
  setState: React.Dispatch<React.SetStateAction<WizardState>>;
  onSkipToDocuments: () => void;
}) {
  return (
    <Card>
      <CardHeader title="Request Details" />
      <CardBody className="flex flex-col gap-4">
        <button
          type="button"
          onClick={onSkipToDocuments}
          className="inline-flex items-center gap-2 self-start text-sm font-medium text-accent hover:underline"
        >
          <UploadCloud className="size-4 shrink-0" aria-hidden="true" />
          Have an invoice, quote, or PO?
        </button>
        <Link to="/app/catalog" className="inline-flex items-center gap-2 self-start text-sm font-medium text-accent hover:underline">
          <ShoppingCart className="size-4 shrink-0" aria-hidden="true" />
          Standard laptop, monitor or more seats? Order from the IT catalog at the agreed price
        </Link>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Category">
            <select
              value={state.requestType}
              onChange={(e) => setState((s) => ({ ...s, requestType: e.target.value as RequestType }))}
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            >
              <option value="hardware">Hardware</option>
              <option value="license">Software License</option>
              <option value="saas">SaaS Subscription</option>
              <option value="reclaim">License Reclaim</option>
            </select>
          </Field>
          <Field label="Department (Optional — defaults to General if skipped)">
            <input
              value={state.department}
              onChange={(e) => setState((s) => ({ ...s, department: e.target.value }))}
              placeholder="e.g. Engineering (or leave empty to auto-extract)"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            />
          </Field>
          <Field label="Estimated Amount in INR (Optional — auto-filled from document)">
            <input
              type="number"
              min={0}
              value={state.amount}
              onChange={(e) => setState((s) => ({ ...s, amount: e.target.value }))}
              placeholder="e.g. 12000 (or leave empty to auto-extract)"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            />
          </Field>
        </div>
        <Field label="Description (Optional)">
          <textarea
            value={state.description}
            onChange={(e) => setState((s) => ({ ...s, description: e.target.value }))}
            rows={3}
            placeholder="What's this for, and why now? (optional)"
            className="w-full resize-none rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
          />
        </Field>
      </CardBody>
    </Card>
  );
}

function StepVendor({
  state,
  setState,
  vendors,
  loading,
  onSkipToDocuments,
}: {
  state: WizardState;
  setState: React.Dispatch<React.SetStateAction<WizardState>>;
  vendors: VendorSummary[] | null;
  loading: boolean;
  onSkipToDocuments: () => void;
}) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 200);
  const filtered = useMemo(
    () => (vendors ?? []).filter((v) => v.name.toLowerCase().includes(debounced.toLowerCase())),
    [vendors, debounced],
  );

  return (
    <Card>
      <CardHeader
        title="Vendor"
        subtitle="Optional if you upload a document"
        action={
          <Button size="sm" variant="ghost" onClick={onSkipToDocuments}>
            Skip to document upload
          </Button>
        }
      />
      <CardBody className="flex flex-col gap-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search vendors…"
            aria-label="Search vendors"
            className="w-full rounded-lg border border-surface-border py-2 pl-9 pr-3 text-sm focus:border-brand-500"
          />
        </div>
        <div className="max-h-72 overflow-y-auto rounded-lg border border-surface-border">
          {loading ? (
            <p className="p-4 text-sm text-slate-400">Loading vendors…</p>
          ) : filtered.length === 0 ? (
            <p className="p-4 text-sm text-slate-400">No vendors match "{search}".</p>
          ) : (
            filtered.map((v) => (
              <button
                key={v.id}
                onClick={() => setState((s) => ({ ...s, vendorId: v.id, vendor: v }))}
                className={`flex w-full items-center justify-between gap-3 border-b border-surface-border px-4 py-2.5 text-left last:border-0 hover:bg-surface-subtle ${
                  state.vendorId === v.id ? "bg-brand-50" : ""
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Building2 className="size-4 text-slate-400" />
                  <span className="text-sm font-medium text-slate-800">{v.name}</span>
                </div>
                <RiskBadge band={v.risk_band} />
              </button>
            ))
          )}
        </div>
        <button
          disabled
          title="Vendor creation isn't available through the current backend API — vendors are onboarded via document intelligence matching."
          className="flex cursor-not-allowed items-center justify-center gap-2 rounded-lg border border-dashed border-surface-border py-2.5 text-sm text-slate-400"
        >
          <Lock className="size-3.5" />
          Add a new vendor
        </button>
      </CardBody>
    </Card>
  );
}

function StepDocuments({
  state,
  setState,
  vendors,
  onProcessingChange,
}: {
  state: WizardState;
  setState: React.Dispatch<React.SetStateAction<WizardState>>;
  vendors: VendorSummary[] | null;
  onProcessingChange?: (busy: boolean) => void;
}) {
  const { user } = useAuth();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);
  const [selectedPreviewIdx, setSelectedPreviewIdx] = useState(0);
  const activePollsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    onProcessingChange?.(uploading || polling);
  }, [uploading, polling, onProcessingChange]);

  const handleFiles = async (files: File[]) => {
    if (!files.length) return;
    setError(null);
    setUploading(true);

    const docIds: string[] = [];
    for (const file of files) {
      try {
        const res = await documentsApi.upload(file, user!.email);
        const docId = res.data.document_id;
        docIds.push(docId);
        activePollsRef.current.add(docId);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Upload failed for one or more files.");
      }
    }
    setUploading(false);

    if (docIds.length === 0) return;

    setPolling(true);

    docIds.forEach((docId) => {
      let attempts = 0;
      const poll = async () => {
        attempts += 1;
        try {
          const docRes = await documentsApi.get(docId);
          const doc = docRes.data;

          setState((s) => {
            const draft = buildDraftFromDocument(doc, vendors, s.department);
            const existingIdx = s.drafts.findIndex((d) => d.id === doc.id);
            let nextDrafts: RequestDraft[];
            if (existingIdx >= 0) {
              const prev = s.drafts[existingIdx];
              nextDrafts = [...s.drafts];
              nextDrafts[existingIdx] = {
                ...draft,
                requestType: prev.requestType,
                department: prev.department || draft.department,
                amount: draft.amount || prev.amount,
                description: prev.description || draft.description,
                vendorId: draft.vendorId ?? prev.vendorId,
                vendor: draft.vendor ?? prev.vendor,
              };
            } else {
              nextDrafts = [...s.drafts, draft];
            }

            const first = nextDrafts[0];
            return {
              ...s,
              drafts: nextDrafts,
              document: s.document && s.document.id !== doc.id ? s.document : doc,
              amount: (!s.amount || s.amount === "0") && first ? first.amount : s.amount,
              vendorId: s.vendorId ?? first?.vendorId ?? null,
              vendor: s.vendor ?? first?.vendor ?? null,
              department: s.department || first?.department || "General",
              description: s.description || first?.description || "",
            };
          });

          if (doc.status === "classified" || doc.status === "failed") {
            activePollsRef.current.delete(doc.id);
            if (activePollsRef.current.size === 0) {
              setPolling(false);
            }
            return;
          }
        } catch {
          // ignore transient poll errors
        }

        if (attempts >= 40) {
          activePollsRef.current.delete(docId);
          if (activePollsRef.current.size === 0) {
            setPolling(false);
          }
          return;
        }

        setTimeout(poll, 1500);
      };

      poll();
    });
  };

  const handleFile = (file: File) => handleFiles([file]);

  const removeDraft = (draftId: string) => {
    setState((s) => {
      const nextDrafts = s.drafts.filter((d) => d.id !== draftId);
      const first = nextDrafts[0];
      return {
        ...s,
        drafts: nextDrafts,
        document: first?.document ?? null,
        amount: first?.amount ?? "",
        vendorId: first?.vendorId ?? null,
        vendor: first?.vendor ?? null,
      };
    });
  };

  const allDocs = useMemo(() => {
    if (state.drafts.length > 0) return state.drafts.map((d) => d.document);
    if (state.document) return [state.document];
    return [];
  }, [state.drafts, state.document]);

  const pipeline = deriveMultiUploadPipeline(allDocs, uploading);

  return (
    <Card>
      <CardHeader
        title="Supporting Documents"
        subtitle={
          state.drafts.length > 1
            ? "Multiple documents detected: Each document is treated as an independent purchase request."
            : undefined
        }
      />
      <CardBody className="flex flex-col gap-4">
        <FileUploader
          multiple
          onFilesSelected={handleFiles}
          onFileSelected={handleFile}
          accept=".pdf,.png,.jpg,.jpeg,.tiff,.tif"
          disabled={uploading || polling}
        />

        {error && <InlineError message={error} />}

        {(uploading || allDocs.length > 0) && (
          <div className="rounded-lg border border-surface-border p-4">
            <LifecycleStepper stages={pipeline} />
          </div>
        )}

        {state.drafts.length > 1 && (
          <div className="space-y-3 rounded-lg border border-surface-border bg-surface-subtle p-3.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-800">
                <Layers className="size-4 text-brand-600" />
                <span>Uploaded Documents ({state.drafts.length}) — Independent Purchase Requests</span>
              </div>
              {polling && (
                <span className="flex items-center gap-1 text-xs text-brand-600 font-medium">
                  <span className="size-2 rounded-full bg-brand-500 animate-pulse" />
                  Classifying & extracting…
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {state.drafts.map((draft, idx) => {
                const dAmount = Number(draft.amount) || 0;
                return (
                  <div
                    key={draft.id}
                    className={`rounded-lg border bg-white p-3 text-xs shadow-sm transition-all ${
                      selectedPreviewIdx === idx ? "border-brand-500 ring-1 ring-brand-500" : "border-surface-border"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 truncate">
                        <FileText className="size-4 shrink-0 text-brand-600" />
                        <span className="truncate font-semibold text-slate-800">
                          Request #{idx + 1}: {draft.document.original_filename}
                        </span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium capitalize ${
                            draft.document.status === "classified"
                              ? "bg-success-50 text-success-700"
                              : draft.document.status === "failed"
                                ? "bg-danger-50 text-danger-700"
                                : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {draft.document.status}
                        </span>
                        <button
                          type="button"
                          onClick={() => removeDraft(draft.id)}
                          className="p-1 text-slate-400 hover:text-danger-600"
                          title="Remove this draft"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </div>

                    <div className="mt-2 grid grid-cols-2 gap-2 border-t border-slate-100 pt-2 text-[11px]">
                      <div>
                        <span className="text-slate-400">Est. Total: </span>
                        <span className="font-semibold text-slate-900">
                          {dAmount > 0 ? formatCurrency(dAmount) : "Extracting…"}
                        </span>
                      </div>
                      <div className="truncate">
                        <span className="text-slate-400">Vendor: </span>
                        <span className="font-medium text-slate-800 truncate">
                          {draft.vendor?.name ?? draft.document.vendor_name_raw ?? "Matching…"}
                        </span>
                      </div>
                    </div>

                    <div className="mt-2 flex justify-end">
                      <Button
                        size="sm"
                        variant={selectedPreviewIdx === idx ? "secondary" : "ghost"}
                        onClick={() => setSelectedPreviewIdx(idx)}
                      >
                        {selectedPreviewIdx === idx ? "Previewing" : "Preview"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {state.drafts.length > 1 && state.drafts[selectedPreviewIdx] && (
          <DocumentPreviewCard
            key={state.drafts[selectedPreviewIdx].id}
            initialDocument={state.drafts[selectedPreviewIdx].document}
            title={`Preview: Request #${selectedPreviewIdx + 1} (${state.drafts[selectedPreviewIdx].document.original_filename ?? ""})`}
            subtitle="Extracted fields and interactive document viewer"
            compact
          />
        )}

        {state.drafts.length <= 1 && state.document && (
          <DocumentPreviewCard
            initialDocument={state.document}
            title="Uploaded Document Preview"
            subtitle={state.document.original_filename ?? undefined}
            compact
          />
        )}

        {state.drafts.length <= 1 && state.document && (state.amount || state.vendor || state.document.vendor_name_raw) && (
          <div className="rounded-lg border border-success-200 bg-success-50 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold text-success-900">
              <Sparkles className="size-4 text-success-600" />
              <span>Details Extracted & Auto-Filled into Request</span>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs text-success-700">Estimated Total</p>
                <p className="font-semibold text-success-950">
                  {state.amount ? formatCurrency(Number(state.amount)) : "Extracting…"}
                </p>
              </div>
              <div>
                <p className="text-xs text-success-700">Vendor</p>
                <p className="font-semibold text-success-950">
                  {state.vendor?.name ?? state.document.vendor_name_raw ?? "Extracting…"}
                </p>
              </div>
              <div>
                <p className="text-xs text-success-700">Department</p>
                <p className="font-semibold text-success-950">{state.department || "General"}</p>
              </div>
            </div>
            <p className="mt-2 text-xs text-success-700">
              All extracted fields will be verified in the Review step where you can confirm or modify them before final submission.
            </p>
          </div>
        )}

        {state.drafts.length <= 1 && state.document?.status === "classified" && (
          <div className="rounded-lg border border-surface-border p-4">
            <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-slate-700">
              <UploadCloud className="size-4 text-brand-600" /> Extracted from {state.document.original_filename}
            </p>
            <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              <ExtractedField label="Vendor" value={state.document.vendor_name_raw} confidence={state.document.confidence_scores?.vendor} />
              <ExtractedField
                label="Total"
                value={state.document.extracted_fields?.total ? formatCurrency(Number(state.document.extracted_fields.total)) : null}
                confidence={state.document.confidence_scores?.total}
              />
              <ExtractedField label="Document Type" value={state.document.document_type} confidence={state.document.confidence_scores?.document_type} />
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function ExtractedField({ label, value, confidence }: { label: string; value: React.ReactNode; confidence?: number }) {
  return (
    <div>
      <p className="text-xs text-slate-400">{label}</p>
      <p className="font-medium text-slate-800">{value ?? "—"}</p>
      {confidence != null && <ConfidenceIndicator score={confidence} compact />}
    </div>
  );
}

function StepReview({
  state,
  setState,
  amount,
  tier,
  vendors,
}: {
  state: WizardState;
  setState: React.Dispatch<React.SetStateAction<WizardState>>;
  amount: number;
  tier: (typeof SPEND_TIERS)[number];
  vendors: VendorSummary[] | null;
}) {
  const [activeDraftIdx, setActiveDraftIdx] = useState(0);
  const [viewMode, setViewMode] = useState<"focus" | "stacked">("focus");

  const isMulti = state.drafts.length > 1;

  const updateDraft = (idx: number, updates: Partial<RequestDraft>) => {
    setState((s) => {
      const nextDrafts = [...s.drafts];
      nextDrafts[idx] = { ...nextDrafts[idx], ...updates };
      return {
        ...s,
        drafts: nextDrafts,
        ...(idx === 0
          ? {
              amount: updates.amount ?? s.amount,
              department: updates.department ?? s.department,
              requestType: updates.requestType ?? s.requestType,
              vendorId: updates.vendorId !== undefined ? updates.vendorId : s.vendorId,
              vendor: updates.vendor !== undefined ? updates.vendor : s.vendor,
              description: updates.description ?? s.description,
            }
          : {}),
      };
    });
  };

  if (isMulti) {
    const activeDraft = state.drafts[activeDraftIdx] ?? state.drafts[0];
    const activeDraftAmount = Number(activeDraft?.amount) || 0;
    const activeDraftTier = resolveSpendTier(activeDraftAmount);

    const invalidDrafts = state.drafts
      .map((d, i) => ({ d, i }))
      .filter(({ d }) => (Number(d.amount) || 0) <= 0 || !d.department.trim());

    return (
      <Card>
        <CardHeader
          title={`Review & Validate (${state.drafts.length} Independent Requests)`}
          subtitle="Each document is treated as an independent purchase request with its own amount, vendor, category, line items, and approval routing."
          action={
            <div className="flex items-center gap-1 rounded-lg border border-surface-border p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setViewMode("focus")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  viewMode === "focus" ? "bg-brand-50 text-brand-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Tabbed Focus
              </button>
              <button
                type="button"
                onClick={() => setViewMode("stacked")}
                className={`rounded px-2.5 py-1 font-medium transition-colors ${
                  viewMode === "stacked" ? "bg-brand-50 text-brand-700 shadow-xs" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Show All Stacked
              </button>
            </div>
          }
        />
        <CardBody className="flex flex-col gap-5">
          {invalidDrafts.length > 0 && (
            <InlineError
              message={`The following requests require attention before continuing: ${invalidDrafts
                .map(({ i, d }) => `Request #${i + 1} (${d.document.original_filename})`)
                .join(", ")}. Please ensure estimated amount is greater than 0 and department is specified.`}
            />
          )}

          {viewMode === "focus" ? (
            <>
              {/* Tab Selector */}
              <div className="flex flex-wrap gap-2 border-b border-surface-border pb-3">
                {state.drafts.map((d, idx) => {
                  const dAmount = Number(d.amount) || 0;
                  const isValid = dAmount > 0 && d.department.trim().length > 0;
                  const isSelected = activeDraftIdx === idx;
                  return (
                    <button
                      key={d.id}
                      type="button"
                      onClick={() => setActiveDraftIdx(idx)}
                      className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-all ${
                        isSelected
                          ? "border-brand-600 bg-brand-50 text-brand-900 shadow-sm ring-1 ring-brand-500"
                          : "border-surface-border bg-white text-slate-700 hover:bg-surface-subtle"
                      }`}
                    >
                      <span className="font-semibold text-slate-900">Request #{idx + 1}</span>
                      <span className="max-w-[130px] truncate text-slate-500">
                        {d.document.original_filename ?? "Doc"}
                      </span>
                      <span className={`font-semibold ${dAmount > 0 ? "text-slate-900" : "text-danger-600"}`}>
                        {dAmount > 0 ? formatCurrency(dAmount) : "₹0"}
                      </span>
                      {!isValid && (
                        <span className="size-2 rounded-full bg-danger-500" title="Needs valid amount or department" />
                      )}
                    </button>
                  );
                })}
              </div>

              {/* Active Draft Form */}
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <h3 className="font-semibold text-sm text-slate-900">
                    Purchase Request #{activeDraftIdx + 1}: {activeDraft.document.original_filename}
                  </h3>
                  <span className="text-xs text-slate-400">
                    Document ID: <code className="text-[11px] text-slate-600">{activeDraft.document.id.slice(0, 8)}</code>
                  </span>
                </div>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="Category">
                    <select
                      value={activeDraft.requestType}
                      onChange={(e) => updateDraft(activeDraftIdx, { requestType: e.target.value as RequestType })}
                      className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                    >
                      <option value="hardware">Hardware</option>
                      <option value="license">Software License</option>
                      <option value="saas">SaaS Subscription</option>
                      <option value="reclaim">License Reclaim</option>
                    </select>
                  </Field>

                  <Field label="Department *">
                    <input
                      value={activeDraft.department}
                      onChange={(e) => updateDraft(activeDraftIdx, { department: e.target.value })}
                      placeholder="e.g. Engineering or General"
                      className={`w-full rounded-lg border px-3 py-2 text-sm focus:border-brand-500 ${
                        !activeDraft.department.trim() ? "border-danger-400 bg-danger-50/30" : "border-surface-border"
                      }`}
                    />
                  </Field>

                  <Field label="Estimated Amount (INR) *">
                    <input
                      type="number"
                      min={0}
                      value={activeDraft.amount}
                      onChange={(e) => updateDraft(activeDraftIdx, { amount: e.target.value })}
                      placeholder="0"
                      className={`w-full rounded-lg border px-3 py-2 text-sm focus:border-brand-500 ${
                        activeDraftAmount <= 0 ? "border-danger-400 bg-danger-50/30" : "border-surface-border"
                      }`}
                    />
                  </Field>

                  <Field label="Vendor">
                    <select
                      value={activeDraft.vendorId ?? ""}
                      onChange={(e) => {
                        const vid = e.target.value || null;
                        const v = vendors?.find((item) => item.id === vid) ?? null;
                        updateDraft(activeDraftIdx, { vendorId: vid, vendor: v });
                      }}
                      className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                    >
                      <option value="">Not linked / Unregistered vendor</option>
                      {vendors?.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.name}
                        </option>
                      ))}
                    </select>
                  </Field>

                  <div className="sm:col-span-2">
                    <Field label="Description">
                      <input
                        value={activeDraft.description}
                        onChange={(e) => updateDraft(activeDraftIdx, { description: e.target.value })}
                        placeholder="Request description (optional)"
                        className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                      />
                    </Field>
                  </div>
                </div>

                <div className="rounded-lg border border-surface-border bg-surface-subtle p-3 text-xs text-slate-600">
                  <span className="font-semibold text-slate-800">Routing Policy:</span> Request #{activeDraftIdx + 1} will be routed as{" "}
                  <span className="font-semibold capitalize text-brand-700">{activeDraftTier.name}</span> spend tier based on the estimated amount of{" "}
                  <span className="font-semibold text-slate-900">{formatCurrency(activeDraftAmount)}</span>.
                  <div className="mt-1 text-slate-500">
                    Approval chain: {activeDraftTier.chain.length ? activeDraftTier.chain.map(titleCase).join(" → ") : "Auto-approved"}
                  </div>
                </div>

                {/* Line items table preview if present */}
                {Array.isArray(activeDraft.document.extracted_fields?.line_items) &&
                  activeDraft.document.extracted_fields.line_items.length > 0 && (
                    <div className="rounded-lg border border-surface-border overflow-hidden">
                      <div className="bg-surface-subtle px-3 py-2 text-xs font-semibold text-slate-700">
                        Extracted Multiline Items ({activeDraft.document.extracted_fields.line_items.length})
                      </div>
                      <div className="max-h-48 overflow-y-auto">
                        <table className="w-full text-left text-xs">
                          <thead className="border-b border-surface-border bg-slate-50 text-slate-500">
                            <tr>
                              <th className="px-3 py-2">Item Description</th>
                              <th className="px-3 py-2 text-right">Qty</th>
                              <th className="px-3 py-2 text-right">Unit Price</th>
                              <th className="px-3 py-2 text-right">Total</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-surface-border">
                            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                            {activeDraft.document.extracted_fields.line_items.map((item: any, liIdx: number) => (
                              <tr key={liIdx} className="hover:bg-surface-subtle/50">
                                <td className="px-3 py-2 text-slate-800">{item.description || item.item || "—"}</td>
                                <td className="px-3 py-2 text-right text-slate-600">{item.quantity ?? "—"}</td>
                                <td className="px-3 py-2 text-right text-slate-600">
                                  {item.unit_price != null ? formatCurrency(Number(item.unit_price)) : "—"}
                                </td>
                                <td className="px-3 py-2 text-right font-medium text-slate-900">
                                  {item.line_total != null || item.total != null
                                    ? formatCurrency(Number(item.line_total ?? item.total))
                                    : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                {/* Interactive Document Preview */}
                <DocumentPreviewCard
                  key={activeDraft.id}
                  initialDocument={activeDraft.document}
                  title={`Attached Document Preview: ${activeDraft.document.original_filename}`}
                  subtitle={`Request #${activeDraftIdx + 1} of ${state.drafts.length}`}
                  compact
                />

                {/* Next / Previous Navigation */}
                <div className="flex items-center justify-between border-t border-surface-border pt-4">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setActiveDraftIdx((i) => Math.max(0, i - 1))}
                    disabled={activeDraftIdx === 0}
                  >
                    Previous Request
                  </Button>
                  <span className="text-xs text-slate-500 font-medium">
                    Reviewing {activeDraftIdx + 1} of {state.drafts.length}
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setActiveDraftIdx((i) => Math.min(state.drafts.length - 1, i + 1))}
                    disabled={activeDraftIdx === state.drafts.length - 1}
                  >
                    Next Request
                  </Button>
                </div>
              </div>
            </>
          ) : (
            /* Stacked View: All requests displayed sequentially */
            <div className="flex flex-col gap-8">
              {state.drafts.map((draft, idx) => {
                const dAmount = Number(draft.amount) || 0;
                const dTier = resolveSpendTier(dAmount);
                return (
                  <div key={draft.id} className="rounded-xl border border-surface-border bg-white p-5 shadow-sm space-y-4">
                    <div className="flex items-center justify-between border-b border-surface-border pb-3">
                      <div>
                        <h4 className="font-semibold text-sm text-slate-900">
                          Purchase Request #{idx + 1}: {draft.document.original_filename}
                        </h4>
                        <p className="text-xs text-slate-400">
                          Document ID: <code className="text-[11px] text-slate-600">{draft.document.id.slice(0, 8)}</code>
                        </p>
                      </div>
                      <span className="text-sm font-bold text-slate-900">
                        {dAmount > 0 ? formatCurrency(dAmount) : "₹0"}
                      </span>
                    </div>

                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label="Category">
                        <select
                          value={draft.requestType}
                          onChange={(e) => updateDraft(idx, { requestType: e.target.value as RequestType })}
                          className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                        >
                          <option value="hardware">Hardware</option>
                          <option value="license">Software License</option>
                          <option value="saas">SaaS Subscription</option>
                          <option value="reclaim">License Reclaim</option>
                        </select>
                      </Field>

                      <Field label="Department *">
                        <input
                          value={draft.department}
                          onChange={(e) => updateDraft(idx, { department: e.target.value })}
                          placeholder="e.g. Engineering or General"
                          className={`w-full rounded-lg border px-3 py-2 text-sm focus:border-brand-500 ${
                            !draft.department.trim() ? "border-danger-400 bg-danger-50/30" : "border-surface-border"
                          }`}
                        />
                      </Field>

                      <Field label="Estimated Amount (INR) *">
                        <input
                          type="number"
                          min={0}
                          value={draft.amount}
                          onChange={(e) => updateDraft(idx, { amount: e.target.value })}
                          placeholder="0"
                          className={`w-full rounded-lg border px-3 py-2 text-sm focus:border-brand-500 ${
                            dAmount <= 0 ? "border-danger-400 bg-danger-50/30" : "border-surface-border"
                          }`}
                        />
                      </Field>

                      <Field label="Vendor">
                        <select
                          value={draft.vendorId ?? ""}
                          onChange={(e) => {
                            const vid = e.target.value || null;
                            const v = vendors?.find((item) => item.id === vid) ?? null;
                            updateDraft(idx, { vendorId: vid, vendor: v });
                          }}
                          className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                        >
                          <option value="">Not linked / Unregistered vendor</option>
                          {vendors?.map((v) => (
                            <option key={v.id} value={v.id}>
                              {v.name}
                            </option>
                          ))}
                        </select>
                      </Field>

                      <div className="sm:col-span-2">
                        <Field label="Description">
                          <input
                            value={draft.description}
                            onChange={(e) => updateDraft(idx, { description: e.target.value })}
                            placeholder="Request description (optional)"
                            className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
                          />
                        </Field>
                      </div>
                    </div>

                    <div className="rounded-lg border border-surface-border bg-surface-subtle p-3 text-xs text-slate-600">
                      <span className="font-semibold text-slate-800">Routing Policy:</span> Request #{idx + 1} routed as{" "}
                      <span className="font-semibold capitalize text-brand-700">{dTier.name}</span> spend tier ({formatCurrency(dAmount)}).
                    </div>

                    <DocumentPreviewCard
                      key={draft.id}
                      initialDocument={draft.document}
                      title={`Preview: ${draft.document.original_filename}`}
                      compact
                    />
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Review & Confirm"
        subtitle="Adjust any values before submitting."
      />
      <CardBody className="flex flex-col gap-5">
        {amount <= 0 && (
          <InlineError message="Estimated amount is required to submit. Please enter the amount below or upload a document with a valid total." />
        )}
        {!state.department.trim() && (
          <InlineError message="Department is required to submit. Please provide a department name below." />
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Category">
            <select
              value={state.requestType}
              onChange={(e) => setState((s) => ({ ...s, requestType: e.target.value as RequestType }))}
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            >
              <option value="hardware">Hardware</option>
              <option value="license">Software License</option>
              <option value="saas">SaaS Subscription</option>
              <option value="reclaim">License Reclaim</option>
            </select>
          </Field>

          <Field label="Department *">
            <input
              value={state.department}
              onChange={(e) => setState((s) => ({ ...s, department: e.target.value }))}
              placeholder="e.g. Engineering or General"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            />
          </Field>

          <Field label="Estimated Amount (INR) *">
            <input
              type="number"
              min={0}
              value={state.amount}
              onChange={(e) => setState((s) => ({ ...s, amount: e.target.value }))}
              placeholder="0"
              className={`w-full rounded-lg border px-3 py-2 text-sm focus:border-brand-500 ${
                amount <= 0 ? "border-danger-400 bg-danger-50/30" : "border-surface-border"
              }`}
            />
          </Field>

          <Field label="Vendor">
            <select
              value={state.vendorId ?? ""}
              onChange={(e) => {
                const vid = e.target.value || null;
                const v = vendors?.find((item) => item.id === vid) ?? null;
                setState((s) => ({ ...s, vendorId: vid, vendor: v }));
              }}
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            >
              <option value="">Not linked / Unregistered vendor</option>
              {vendors?.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
          </Field>

          <div className="sm:col-span-2">
            <Field label="Description">
              <input
                value={state.description}
                onChange={(e) => setState((s) => ({ ...s, description: e.target.value }))}
                placeholder="Request description (optional)"
                className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
              />
            </Field>
          </div>
        </div>

        <div className="rounded-lg border border-surface-border bg-surface-subtle p-3 text-xs text-slate-600">
          <span className="font-semibold text-slate-800">Routing Policy:</span> This request will be routed as{" "}
          <span className="font-semibold capitalize text-brand-700">{tier.name}</span> spend tier based on the estimated amount of{" "}
          <span className="font-semibold text-slate-900">{formatCurrency(amount)}</span>.
        </div>

        {state.document && (
          <DocumentPreviewCard
            initialDocument={state.document}
            title="Attached Supporting Document"
            subtitle={state.document.original_filename ?? undefined}
            compact
          />
        )}

        {state.document?.needs_review && (
          <div className="flex items-start gap-2 rounded-lg border border-warning-50 bg-warning-50 px-3 py-2 text-sm text-warning-700">
            <Info className="mt-0.5 size-4 shrink-0" />
            <span>The attached document has low-confidence fields and will be queued for verification under Documents.</span>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function StepSubmit({
  state,
  amount,
  tier,
  submitting,
  error,
  onSubmit,
}: {
  state: WizardState;
  amount: number;
  tier: (typeof SPEND_TIERS)[number];
  submitting: boolean;
  error: string | null;
  onSubmit: () => void;
}) {
  const isMulti = state.drafts.length > 1;
  const totalAmount = isMulti
    ? state.drafts.reduce((acc, d) => acc + (Number(d.amount) || 0), 0)
    : amount;

  return (
    <Card>
      <CardHeader
        title={isMulti ? `Submit ${state.drafts.length} Purchase Requests` : "Submit"}
        subtitle={
          isMulti
            ? "Each request below will be created independently and routed to its designated approval chain."
            : "How this request will be routed"
        }
      />
      <CardBody className="flex flex-col gap-4">
        {isMulti ? (
          <div className="space-y-3">
            <div className="divide-y divide-surface-border rounded-lg border border-surface-border bg-surface-subtle">
              {state.drafts.map((d, idx) => {
                const dAmount = Number(d.amount) || 0;
                const dTier = resolveSpendTier(dAmount);
                return (
                  <div key={d.id} className="p-3 text-xs">
                    <div className="flex items-center justify-between font-semibold text-slate-800">
                      <span>Request #{idx + 1}: {d.document.original_filename ?? "Document"}</span>
                      <span className="text-sm font-bold text-slate-900">{formatCurrency(dAmount)}</span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-slate-500">
                      <span>Category: <span className="font-medium text-slate-700 capitalize">{d.requestType}</span></span>
                      <span>Department: <span className="font-medium text-slate-700">{d.department}</span></span>
                      <span>Vendor: <span className="font-medium text-slate-700">{d.vendor?.name ?? d.document.vendor_name_raw ?? "Unregistered"}</span></span>
                      <span>Routing: <span className="font-medium text-brand-700 capitalize">{dTier.name} Tier</span></span>
                    </div>
                    <div className="mt-1 text-slate-400">
                      Chain: {dTier.chain.length ? dTier.chain.map(titleCase).join(" → ") : "Auto-approved"}
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="rounded-lg border border-surface-border p-4 bg-white">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Total Across All Requests</p>
                  <p className="text-xs text-slate-500">{state.drafts.length} independent requests to be submitted</p>
                </div>
                <p className="text-xl font-bold text-slate-900">{formatCurrency(totalAmount)}</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-surface-border p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-400">Approval Chain</p>
            <p className="mt-1 text-sm text-slate-700">
              {tier.chain.length ? tier.chain.map(titleCase).join(" → ") : "Auto-approved — no manual approval required"}
            </p>
            <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-400">Estimated Processing Time</p>
            <p className="mt-1 text-sm text-slate-700">Up to {SLA_APPROVAL_TIMEOUT_HOURS} hours per approval stage (SLA policy)</p>
            <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-400">Total Amount</p>
            <p className="mt-1 text-lg font-semibold text-slate-900">{formatCurrency(amount)}</p>
          </div>
        )}

        {error && <InlineError message={error} />}

        <Button size="lg" loading={submitting} onClick={onSubmit}>
          {isMulti
            ? `Submit ${state.drafts.length} Purchase Requests`
            : "Submit Purchase Request"}
        </Button>
      </CardBody>
    </Card>
  );
}

function Field({ label, children, static: isStatic }: { label: string; children: React.ReactNode; static?: boolean }) {
  if (isStatic) {
    return (
      <div>
        <dt className="text-xs text-slate-400">{label}</dt>
        <dd className="mt-0.5 font-medium text-slate-800">{children}</dd>
      </div>
    );
  }
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}
