import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Copy, Download, FileWarning } from "lucide-react";
import { DocumentAmount } from "@/components/documents/DocumentAmount";
import { TaxCheckSection } from "@/components/documents/TaxCheckSection";
import { ExtractionDetails } from "@/components/documents/ExtractionDetails";
import { DocumentControls } from "@/components/controls/DocumentControls";
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
import { DocketHeader, RefCopy } from "@/components/ui/DocketHeader";
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
  const [docNumber, setDocNumber] = useState("");
  const [docDate, setDocDate] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState<string | null>(null);

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewFailed, setPreviewFailed] = useState(false);

  useEffect(() => {
    if (!doc?.id) return;
    let active = true;
    let url: string | null = null;
    setPreviewLoading(true);
    setPreviewFailed(false);
    documentsApi
      .getFileUrl(doc.id)
      .then((blobUrl: string) => {
        if (!active) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        url = blobUrl;
        setPreviewUrl(blobUrl);
      })
      .catch(() => {
        if (active) setPreviewFailed(true);
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
      });

    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [doc?.id]);

  useEffect(() => {
    if (!doc) return;
    setVendorName(doc.vendor_name_raw ?? "");
    setDocumentType((doc.document_type as DocumentType) ?? "invoice");
    setTotal(doc.extracted_fields?.total != null ? String(doc.extracted_fields.total) : "");
    setDocNumber(String(doc.extracted_fields?.invoice_number ?? doc.extracted_fields?.document_number ?? ""));
    setDocDate(String(doc.extracted_fields?.invoice_date ?? doc.extracted_fields?.document_date ?? ""));
  }, [doc]);

  const save = async (mode: "confirm" | "correct") => {
    if (!doc || !user) return;
    setSaving(true);
    setSaveError(null);
    setSaveSuccess(null);
    try {
      const extracted: Record<string, unknown> = { ...(doc.extracted_fields ?? {}), total: total ? Number(total) : null };
      if (docNumber) {
        extracted.document_number = docNumber;
        if (documentType === "invoice") extracted.invoice_number = docNumber;
      }
      if (docDate) {
        extracted.document_date = docDate;
        if (documentType === "invoice") extracted.invoice_date = docDate;
      }
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

  if (loading && !doc) {
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
      <DocketHeader
        reference={
          <>
            <RefCopy prefix="DOC" id={doc.id} />
            <span className="text-13 text-ink-3">{documentTypeLabel(doc.document_type)}</span>
          </>
        }
        title={doc.original_filename ?? "Document"}
        status={<DocumentStatusBadge status={doc.status} needsReview={doc.needs_review} />}
        meta={<span>Received {formatDateTime(doc.uploaded_at)}</span>}
      />

      <DocumentControls extracted={doc.extracted_fields ?? {}} documentId={doc.id} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Left: Document Preview & Details */}
        <Card className="flex flex-col">
          <CardHeader
            title="Document Preview"
            action={
              <Button
                variant="secondary"
                size="sm"
                icon={<Download className="size-3.5" />}
                onClick={() => doc && documentsApi.downloadFile(doc.id, doc.original_filename ?? "document")}
              >
                Download
              </Button>
            }
          />
          <CardBody className="flex flex-1 flex-col gap-3">
            {previewLoading ? (
              <div className="flex h-64 flex-col items-center justify-center gap-2 rounded-lg border border-surface-border bg-surface-subtle p-4">
                <Skeleton className="h-44 w-full" />
                <span className="text-xs text-slate-400">Loading document preview...</span>
              </div>
            ) : previewUrl && (doc.file_type === "image" || doc.original_filename?.match(/\.(png|jpe?g|webp|gif)$/i)) ? (
              <div className="flex max-h-80 items-center justify-center overflow-hidden rounded-lg border border-surface-border bg-slate-900/5 p-2">
                <img
                  src={previewUrl}
                  alt={doc.original_filename ?? "Document"}
                  className="max-h-72 w-auto max-w-full rounded object-contain shadow-sm"
                />
              </div>
            ) : previewUrl && (doc.file_type === "pdf" || doc.original_filename?.toLowerCase().endsWith(".pdf")) ? (
              <div className="relative h-72 w-full overflow-hidden rounded-lg border border-surface-border bg-slate-100">
                <iframe
                  src={previewUrl}
                  title="PDF Preview"
                  className="size-full rounded-lg border-0"
                />
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-surface-border bg-surface-subtle p-6 text-center">
                <div className={`flex size-14 items-center justify-center rounded-xl ${FILE_ICON_BG[doc.file_type ?? "pdf"] ?? "bg-slate-100 text-slate-500"}`}>
                  <FileWarning className="size-6" />
                </div>
                <p className="text-sm font-medium text-slate-700">{doc.original_filename}</p>
                <p className="text-xs text-slate-400">
                  {previewFailed ? "Preview could not be loaded." : "Direct preview not supported for this file type."}
                </p>
              </div>
            )}

            <dl className="mt-2 w-full space-y-2 border-t border-rule pt-3 text-left text-sm">
              <div className="flex items-baseline justify-between gap-4">
                <dt className="shrink-0 text-ink-3">Received</dt>
                <dd className="min-w-0 break-words text-right font-medium text-ink">
                  {doc.source === "email" ? `By email from ${doc.source_sender ?? "unknown sender"}`
                    : doc.source === "folder" ? "From the shared folder"
                    : `Uploaded by ${doc.uploaded_by ?? "—"}`}
                </dd>
              </div>
              <div className="flex justify-between gap-4"><dt className="text-ink-3">Uploaded</dt><dd className="text-right text-ink">{formatDateTime(doc.uploaded_at)}</dd></div>
              <div className="flex justify-between gap-4"><dt className="text-ink-3">File type</dt><dd className="uppercase font-medium text-ink">{doc.file_type ?? "—"}</dd></div>
              {doc.reviewed_by && (
                <div className="flex justify-between gap-4"><dt className="text-ink-3">Reviewed by</dt><dd className="min-w-0 break-words text-right text-ink">{doc.reviewed_by}</dd></div>
              )}
            </dl>
          </CardBody>
        </Card>

        {/* Center: extracted fields, editable */}
        <Card>
          <CardHeader title="Extracted Fields" subtitle="Correct any low-confidence values before confirming" />
          <CardBody className="flex flex-col gap-4">
            <FieldRow label="Vendor Name" confidence={confidences.vendor ?? confidences.vendor_name}>
              <input aria-label="Vendor name" value={vendorName} onChange={(e) => setVendorName(e.target.value)} className="field" />
            </FieldRow>
            <FieldRow label="Document Type" confidence={confidences.document_type}>
              <select aria-label="Document type" value={documentType} onChange={(e) => setDocumentType(e.target.value as DocumentType)} className="field">
                <option value="po">Purchase Order</option>
                <option value="invoice">Invoice</option>
                <option value="quote">Quote</option>
                <option value="other">Other</option>
              </select>
              {doc.document_type === "invoice" && (
                <p className="mt-1 text-xs text-slate-500">
                  {doc.extracted_fields?.po_reference
                    ? `PO-backed invoice — cites purchase order ${String(doc.extracted_fields.po_reference)}`
                    : "Non-PO invoice — no purchase order cited"}
                </p>
              )}
              {doc.document_type === "other" && (
                <p className="mt-1 text-xs text-slate-500">Not an invoice, PO or quote — check it and choose the right type.</p>
              )}
            </FieldRow>
            <FieldRow label="Total" confidence={confidences.total}>
              <input type="number" aria-label="Total" value={total} onChange={(e) => setTotal(e.target.value)} className="field" />
              {doc.extracted_fields?.total != null && (
                <p className="mt-1 text-xs text-slate-500">
                  <DocumentAmount doc={doc} />
                </p>
              )}
            </FieldRow>
            <FieldRow label="Document Number" confidence={confidences.document_number}>
              <input aria-label="Document number" value={docNumber} onChange={(e) => setDocNumber(e.target.value)} className="field" />
            </FieldRow>
            <FieldRow label="Document Date" confidence={confidences.document_date}>
              <input type="date" aria-label="Document date" value={docDate} onChange={(e) => setDocDate(e.target.value)} className="field" />
            </FieldRow>
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

      {doc.tax_check && <TaxCheckSection tax={doc.tax_check} />}

      {/* AI processing panel */}
      <Card>
        <CardHeader
          title="Extraction results"
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

      <ExtractionDetails doc={doc} />
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
