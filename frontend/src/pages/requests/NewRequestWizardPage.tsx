import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, CheckCircle2, Info, Lock, Search, UploadCloud } from "lucide-react";
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
import { InlineError, InlineSuccess, InlineInfo } from "@/components/ui/ErrorState";
import { RiskBadge } from "@/components/ui/Badge";
import { formatCurrency, formatConfidence, titleCase } from "@/lib/format";
import { SPEND_TIERS, SLA_APPROVAL_TIMEOUT_HOURS, CONFIDENCE_REVIEW_THRESHOLD } from "@/lib/constants";
import { deriveUploadPipeline } from "@/lib/documentPipeline";
import type { CreatePurchaseRequestBody, DocumentRecord, RequestType, VendorSummary } from "@/types/api";
import { ApiError } from "@/api/client";

const STEPS = ["Details", "Vendor", "Documents", "Review", "Submit"];

interface WizardState {
  requestType: RequestType;
  department: string;
  amount: string;
  description: string;
  vendorId: string | null;
  vendor: VendorSummary | null;
  document: DocumentRecord | null;
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
  });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState<{ id: string; status: string; tier: string } | null>(null);

  const amountNum = Number(state.amount) || 0;
  const tier = resolveSpendTier(amountNum);

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));

  const canProceedFromDetails = state.department.trim().length > 0 && amountNum > 0;

  const submit = async () => {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const body: CreatePurchaseRequestBody = {
        request_type: state.requestType,
        requested_by: user!.email,
        department: state.department,
        vendor_id: state.vendorId,
        amount: amountNum,
        currency: "INR",
        comments: state.description || undefined,
      };
      const res = await requestsApi.create(body);
      setSubmitted({ id: res.data.id, status: res.data.status ?? "pending_approval", tier: res.data.spend_tier ?? tier.name });
    } catch (e) {
      setSubmitError(e instanceof ApiError ? e.message : "Unable to submit the request.");
    } finally {
      setSubmitting(false);
    }
  };

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

      {step === 0 && <StepDetails state={state} setState={setState} />}
      {step === 1 && <StepVendor state={state} setState={setState} />}
      {step === 2 && <StepDocuments state={state} setState={setState} />}
      {step === 3 && <StepReview state={state} amount={amountNum} tier={tier} />}
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
          <Button onClick={next} disabled={step === 0 && !canProceedFromDetails}>
            Continue
          </Button>
        )}
      </div>
    </div>
  );
}

function StepDetails({ state, setState }: { state: WizardState; setState: React.Dispatch<React.SetStateAction<WizardState>> }) {
  return (
    <Card>
      <CardHeader title="Request Details" subtitle="What are you requesting, and for which department?" />
      <CardBody className="flex flex-col gap-4">
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
          <Field label="Department">
            <input
              value={state.department}
              onChange={(e) => setState((s) => ({ ...s, department: e.target.value }))}
              placeholder="Engineering"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            />
          </Field>
          <Field label="Estimated Amount (INR)">
            <input
              type="number"
              min={0}
              value={state.amount}
              onChange={(e) => setState((s) => ({ ...s, amount: e.target.value }))}
              placeholder="1200"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
            />
          </Field>
        </div>
        <Field label="Description">
          <textarea
            value={state.description}
            onChange={(e) => setState((s) => ({ ...s, description: e.target.value }))}
            rows={3}
            placeholder="What's this for, and why now?"
            className="w-full resize-none rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
          />
        </Field>
      </CardBody>
    </Card>
  );
}

function StepVendor({ state, setState }: { state: WizardState; setState: React.Dispatch<React.SetStateAction<WizardState>> }) {
  const [search, setSearch] = useState("");
  const debounced = useDebounce(search, 200);
  const { data: vendors, loading } = useApi(() => vendorsApi.list(200), []);
  const filtered = useMemo(
    () => (vendors ?? []).filter((v) => v.name.toLowerCase().includes(debounced.toLowerCase())),
    [vendors, debounced],
  );

  return (
    <Card>
      <CardHeader title="Vendor" subtitle="Select the vendor this request is for" />
      <CardBody className="flex flex-col gap-4">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search vendors…"
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
        {!state.vendorId && (
          <p className="text-xs text-slate-400">Optional — you can continue without linking a vendor.</p>
        )}
      </CardBody>
    </Card>
  );
}

function StepDocuments({ state, setState }: { state: WizardState; setState: React.Dispatch<React.SetStateAction<WizardState>> }) {
  const { user } = useAuth();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [polling, setPolling] = useState(false);

  const handleFile = async (file: File) => {
    setError(null);
    setUploading(true);
    try {
      const res = await documentsApi.upload(file, user!.email);
      setUploading(false);
      setPolling(true);
      let attempts = 0;
      const poll = async () => {
        attempts += 1;
        const doc = await documentsApi.get(res.data.document_id);
        setState((s) => ({ ...s, document: doc.data }));
        if (doc.data.status === "classified" || doc.data.status === "failed" || attempts >= 10) {
          setPolling(false);
          return;
        }
        setTimeout(poll, 1200);
      };
      poll();
    } catch (e) {
      setUploading(false);
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    }
  };

  const pipeline = deriveUploadPipeline(state.document, uploading);

  return (
    <Card>
      <CardHeader
        title="Supporting Documents"
        subtitle="Optional — attach a purchase order, invoice, or quote for reference"
      />
      <CardBody className="flex flex-col gap-4">
        <InlineInfo message="Documents are processed independently by the Document Intelligence pipeline — they aren't stored as a formal link on the request record, but their extracted vendor/amount can help fill in your review step below." />
        <FileUploader onFileSelected={handleFile} accept=".pdf,.png,.jpg,.jpeg" disabled={uploading || polling} />
        {error && <InlineError message={error} />}
        {(uploading || state.document) && (
          <div className="rounded-lg border border-surface-border p-4">
            <LifecycleStepper stages={pipeline} />
          </div>
        )}
        {state.document?.status === "classified" && (
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

function StepReview({ state, amount, tier }: { state: WizardState; amount: number; tier: (typeof SPEND_TIERS)[number] }) {
  return (
    <Card>
      <CardHeader title="Review" subtitle="Confirm the details before submitting" />
      <CardBody>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-3">
          <Field label="Category" static>
            <span className="capitalize">{state.requestType}</span>
          </Field>
          <Field label="Department" static>
            {state.department || "—"}
          </Field>
          <Field label="Amount" static>
            {formatCurrency(amount)}
          </Field>
          <Field label="Vendor" static>
            {state.vendor?.name ?? "Not linked"}
          </Field>
          <Field label="Routing" static>
            <span className="capitalize">{tier.name}</span>
          </Field>
        </dl>
        {state.description && (
          <div className="mt-4 border-t border-surface-border pt-4">
            <p className="text-xs text-slate-400">Description</p>
            <p className="mt-1 text-sm text-slate-700">{state.description}</p>
          </div>
        )}
        {state.document?.needs_review && (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-warning-50 bg-warning-50 px-3 py-2 text-sm text-warning-700">
            <Info className="mt-0.5 size-4 shrink-0" />
            <span>The attached document has low-confidence fields and needs review under Documents after submitting.</span>
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
  return (
    <Card>
      <CardHeader title="Submit" subtitle="Here's how this request will be routed" />
      <CardBody className="flex flex-col gap-4">
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
        {error && <InlineError message={error} />}
        <Button size="lg" loading={submitting} onClick={onSubmit}>
          Submit Purchase Request
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
