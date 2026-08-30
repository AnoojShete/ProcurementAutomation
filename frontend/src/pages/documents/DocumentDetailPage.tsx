import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Copy, FileWarning, Sparkles } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { documentsApi } from "@/api/documents";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, DocumentStatusBadge } from "@/components/ui/Badge";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { documentTypeLabel, formatConfidence, formatDateTime } from "@/lib/format";
import { CONFIDENCE_REVIEW_THRESHOLD } from "@/lib/constants";
import type { DocumentType } from "@/types/api";
import { ApiError } from "@/api/client";

const FILE_ICON_BG: Record<string, string> = { pdf: "bg-danger-50 text-danger-600", image: "bg-brand-50 text-brand-600" };

export function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { data: doc, loading, error, reload } = useApi(() => documentsApi.get(id!), [id]);
  usePageHeader(doc?.original_filename ?? "Document", "Documents");

  const [vendorName, setVendorName] = useState("");
  const [documentType, setDocumentType] = useState<DocumentType>("invoice");
  const [total, setTotal] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!doc) return;
    setVendorName(doc.vendor_name_raw ?? "");
    setDocumentType((doc.document_type as DocumentType) ?? "invoice");
    setTotal(doc.extracted_fields?.total != null ? String(doc.extracted_fields.total) : "");
  }, [doc]);

  const save = async (mode: "confirm" | "correct") => {
    if (!doc || !user) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      const extracted = { ...(doc.extracted_fields ?? {}), total: total ? Number(total) : null };
      await documentsApi.submitReview(doc.id, {
        reviewed_by: user.email,
        vendor_name: vendorName,
        extracted_fields: extracted,
        document_type: documentType,
      });
      setSaveSuccess(mode === "confirm" ? "Confirmed as correct." : "Correction saved.");
      reload();
    } catch (e) {
      setSaveError(e instanceof ApiError ? e.message : "Unable to save.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Skeleton className="h-72" />
        <Skeleton className="h-72 lg:col-span-2" />
      </div>
    );
  }
  if (error || !doc) return <ErrorState message={error ?? "Document not found."} onRetry={reload} />;

  const confidences = doc.confidence_scores ?? {};

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{doc.original_filename ?? "Document"}</h1>
        <DocumentStatusBadge status={doc.status} needsReview={doc.needs_review} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Left: file placeholder — no preview endpoint exists in the current API */}
        <Card>
          <CardHeader title="Document" />
          <CardBody className="flex flex-col items-center gap-3 text-center">
            <div className={`flex size-16 items-center justify-center rounded-xl ${FILE_ICON_BG[doc.file_type ?? "pdf"] ?? "bg-slate-100 text-slate-500"}`}>
              <FileWarning className="size-7" />
            </div>
            <p className="text-sm font-medium text-slate-800">{doc.original_filename}</p>
            <p className="text-xs text-slate-400">
              File preview isn't exposed by the API in this environment — the original is stored in object storage,
              accessible to operators outside this app.
            </p>
            <dl className="mt-2 w-full space-y-2 border-t border-surface-border pt-3 text-left text-sm">
              <div className="flex justify-between"><dt className="text-slate-400">Uploaded by</dt><dd className="text-slate-700">{doc.uploaded_by ?? "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-400">Uploaded</dt><dd className="text-slate-700">{formatDateTime(doc.uploaded_at)}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-400">File type</dt><dd className="uppercase text-slate-700">{doc.file_type ?? "—"}</dd></div>
              {doc.reviewed_by && (
                <div className="flex justify-between"><dt className="text-slate-400">Reviewed by</dt><dd className="text-slate-700">{doc.reviewed_by}</dd></div>
              )}
            </dl>
          </CardBody>
        </Card>

        {/* Center: extracted fields, editable */}
        <Card>
          <CardHeader title="Extracted Fields" subtitle="Correct any low-confidence values before confirming" />
          <CardBody className="flex flex-col gap-4">
            <FieldRow label="Vendor Name" confidence={confidences.vendor ?? confidences.vendor_name}>
              <input value={vendorName} onChange={(e) => setVendorName(e.target.value)} className="w-full rounded-lg border border-surface-border px-3 py-1.5 text-sm focus:border-brand-500" />
            </FieldRow>
            <FieldRow label="Document Type" confidence={confidences.document_type}>
              <select value={documentType} onChange={(e) => setDocumentType(e.target.value as DocumentType)} className="w-full rounded-lg border border-surface-border px-3 py-1.5 text-sm focus:border-brand-500">
                <option value="po">Purchase Order</option>
                <option value="invoice">Invoice</option>
                <option value="quote">Quote</option>
              </select>
            </FieldRow>
            <FieldRow label="Total" confidence={confidences.total}>
              <input type="number" value={total} onChange={(e) => setTotal(e.target.value)} className="w-full rounded-lg border border-surface-border px-3 py-1.5 text-sm focus:border-brand-500" />
            </FieldRow>
            {doc.extracted_fields?.document_number != null && (
              <FieldRow
                label="Document Number"
                confidence={confidences.document_number}
                readOnlyValue={String(doc.extracted_fields.document_number)}
              />
            )}
            {saveError && <InlineError message={saveError} />}
            {saveSuccess && <InlineSuccess message={saveSuccess} />}
            <div className="flex gap-2 pt-2">
              <Button variant="secondary" loading={saving} onClick={() => save("confirm")}>
                <CheckCircle2 className="size-4" /> Confirm as Correct
              </Button>
              <Button loading={saving} onClick={() => save("correct")}>
                Save Correction
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      {/* AI processing panel */}
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-1.5">
              <Sparkles className="size-4 text-intel-600" /> Document Intelligence
            </span>
          }
        />
        <CardBody>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <SummaryStat label="Classification" value={documentTypeLabel(doc.document_type)} />
            <SummaryStat label="Overall Confidence" value={formatConfidence(doc.overall_confidence)} />
            <SummaryStat
              label="Review Status"
              value={doc.needs_review ? "Needs Review" : "Auto-completed"}
              tone={doc.needs_review ? "warning" : "success"}
            />
            <SummaryStat
              label="Duplicate Check"
              value={doc.is_likely_duplicate ? "Likely duplicate" : "No duplicate found"}
              tone={doc.is_likely_duplicate ? "danger" : "success"}
            />
          </div>
          {doc.overall_confidence != null && doc.overall_confidence < CONFIDENCE_REVIEW_THRESHOLD && (
            <div className="mt-4 flex items-start gap-2 rounded-lg border border-warning-50 bg-warning-50 px-3 py-2 text-sm text-warning-700">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span>
                Overall confidence ({formatConfidence(doc.overall_confidence)}) is below the {formatConfidence(CONFIDENCE_REVIEW_THRESHOLD)} auto-complete threshold — this document was routed to manual review.
              </span>
            </div>
          )}
          {doc.is_likely_duplicate && doc.duplicate_of_document_id && (
            <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
              <Copy className="size-3.5" /> Possible duplicate of document{" "}
              <span className="font-mono text-xs">{doc.duplicate_of_document_id.slice(0, 8)}</span>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function FieldRow({
  label,
  confidence,
  children,
  readOnlyValue,
}: {
  label: string;
  confidence?: number;
  children?: React.ReactNode;
  readOnlyValue?: string;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-sm font-medium text-slate-700">{label}</label>
        {confidence != null && <ConfidenceIndicator score={confidence} compact />}
      </div>
      {children ?? <p className="text-sm text-slate-800">{readOnlyValue}</p>}
    </div>
  );
}

function SummaryStat({ label, value, tone }: { label: string; value: string; tone?: "success" | "warning" | "danger" }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <div className="mt-1">{tone ? <Badge tone={tone}>{value}</Badge> : <p className="text-sm font-medium text-slate-800">{value}</p>}</div>
    </div>
  );
}
