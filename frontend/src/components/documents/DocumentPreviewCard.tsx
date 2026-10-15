import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Download, ExternalLink, Eye, FileText, FileWarning, Maximize2 } from "lucide-react";
import { documentsApi } from "@/api/documents";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge, DocumentStatusBadge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { documentTypeLabel, formatDateTime } from "@/lib/format";
import type { DocumentRecord } from "@/types/api";
import { DocumentAmount } from "./DocumentAmount";

const FILE_ICON_BG: Record<string, string> = {
  pdf: "bg-danger-50 text-danger-600",
  image: "bg-brand-50 text-brand-600",
};

interface DocumentPreviewCardProps {
  documentId?: string | null;
  initialDocument?: DocumentRecord | null;
  title?: string;
  subtitle?: string;
  className?: string;
  compact?: boolean;
}

export function DocumentPreviewCard({
  documentId,
  initialDocument,
  title = "Supporting Document Preview",
  subtitle,
  className = "",
  compact = false,
}: DocumentPreviewCardProps) {
  const effectiveId = initialDocument?.id ?? documentId;
  const [doc, setDoc] = useState<DocumentRecord | null>(initialDocument ?? null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  // Load document metadata if only documentId was passed
  useEffect(() => {
    if (initialDocument) {
      setDoc(initialDocument);
      return;
    }
    if (!effectiveId) {
      setDoc(null);
      return;
    }

    let active = true;
    setLoadingDoc(true);
    documentsApi
      .get(effectiveId)
      .then((res) => {
        if (active) setDoc(res.data);
      })
      .catch(() => {
        if (active) setDoc(null);
      })
      .finally(() => {
        if (active) setLoadingDoc(false);
      });

    return () => {
      active = false;
    };
  }, [effectiveId, initialDocument]);

  // Load preview blob URL
  useEffect(() => {
    if (!effectiveId) {
      setPreviewUrl(null);
      return;
    }

    let active = true;
    let url: string | null = null;
    setPreviewLoading(true);
    setPreviewError(false);

    documentsApi
      .getFileUrl(effectiveId)
      .then((blobUrl: string) => {
        if (!active) {
          URL.revokeObjectURL(blobUrl);
          return;
        }
        url = blobUrl;
        setPreviewUrl(blobUrl);
      })
      .catch(() => {
        if (active) setPreviewError(true);
      })
      .finally(() => {
        if (active) setPreviewLoading(false);
      });

    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [effectiveId]);

  if (!effectiveId) return null;

  if (loadingDoc && !doc) {
    return (
      <Card className={className}>
        <CardHeader title={title} subtitle={subtitle} />
        <CardBody className="flex flex-col gap-3 p-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-4 w-3/4" />
        </CardBody>
      </Card>
    );
  }

  const filename = doc?.original_filename ?? `document-${effectiveId.slice(0, 8)}`;
  const isImage =
    doc?.file_type === "image" ||
    filename.toLowerCase().endsWith(".png") ||
    filename.toLowerCase().endsWith(".jpg") ||
    filename.toLowerCase().endsWith(".jpeg") ||
    filename.toLowerCase().endsWith(".webp");
  const isPdf = doc?.file_type === "pdf" || filename.toLowerCase().endsWith(".pdf");

  return (
    <>
      <Card className={className}>
        <CardHeader
          title={title}
          subtitle={subtitle}
          action={
            <div className="flex items-center gap-2">
              {doc?.id && (
                <Link
                  to={`/app/documents/${doc.id}`}
                  className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
                  title="View complete document details and OCR extraction"
                >
                  <ExternalLink className="size-3" /> Full Analysis
                </Link>
              )}
              <Button
                variant="secondary"
                size="sm"
                icon={<Download className="size-3.5" />}
                onClick={() => documentsApi.downloadFile(effectiveId, filename)}
                title="Download original file"
              >
                Download
              </Button>
            </div>
          }
        />
        <CardBody className="flex flex-col gap-3 p-4">
          {previewLoading ? (
            <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-lg border border-surface-border bg-surface-subtle p-4">
              <Skeleton className="h-40 w-full max-w-xs" />
              <span className="text-xs text-slate-400">Loading document preview...</span>
            </div>
          ) : previewUrl && isImage ? (
            <div className="group relative flex max-h-80 items-center justify-center overflow-hidden rounded-lg border border-surface-border bg-slate-900/5 p-2">
              <img
                src={previewUrl}
                alt={filename}
                className="max-h-72 w-auto max-w-full rounded object-contain shadow-sm cursor-pointer transition-transform duration-200 group-hover:scale-[1.01]"
                onClick={() => setModalOpen(true)}
              />
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className="absolute bottom-3 right-3 flex items-center gap-1 rounded-md bg-slate-900/80 px-2 py-1 text-xs font-medium text-white shadow backdrop-blur transition-opacity hover:bg-slate-900"
              >
                <Maximize2 className="size-3.5" /> Enlarge
              </button>
            </div>
          ) : previewUrl && isPdf ? (
            <div className="relative h-72 w-full overflow-hidden rounded-lg border border-surface-border bg-slate-100">
              <iframe
                src={previewUrl}
                title="Document Preview"
                className="size-full rounded-lg border-0"
              />
              <div className="absolute top-2 right-2 flex gap-1">
                <Button
                  size="sm"
                  variant="secondary"
                  className="bg-white/90 backdrop-blur shadow-sm text-xs"
                  onClick={() => setModalOpen(true)}
                  icon={<Maximize2 className="size-3" />}
                >
                  Full View
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-surface-border bg-surface-subtle p-6 text-center">
              <div
                className={`flex size-12 items-center justify-center rounded-xl ${
                  FILE_ICON_BG[doc?.file_type ?? "pdf"] ?? "bg-slate-100 text-slate-500"
                }`}
              >
                <FileWarning className="size-6" />
              </div>
              <p className="text-sm font-medium text-slate-700">{filename}</p>
              <p className="text-xs text-slate-400">
                {previewError ? "Preview unavailable. Click Download to inspect." : "Direct inline preview not supported for this file."}
              </p>
            </div>
          )}

          {!compact && (
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2 border-t border-surface-border pt-3 text-xs">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-slate-900 truncate max-w-xs">{filename}</span>
                {doc?.document_type && (
                  <Badge tone="brand">{documentTypeLabel(doc.document_type)}</Badge>
                )}
                {doc?.status && (
                  <DocumentStatusBadge status={doc.status} needsReview={doc.needs_review} />
                )}
              </div>

              <div className="flex items-center gap-3 text-slate-500">
                {doc?.vendor_name_raw && (
                  <span>
                    Vendor: <b className="text-slate-700">{doc.vendor_name_raw}</b>
                  </span>
                )}
                {doc?.extracted_fields?.total != null && (
                  <span>
                    Total: <b className="text-slate-900"><DocumentAmount doc={doc} /></b>
                  </span>
                )}
                {doc?.uploaded_at && (
                  <span>Uploaded {formatDateTime(doc.uploaded_at)}</span>
                )}
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Lightbox / Full View Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={filename}
        size="lg"
        footer={
          <div className="flex w-full items-center justify-between">
            <span className="text-xs text-slate-500">
              {doc?.uploaded_by && `Uploaded by ${doc.uploaded_by} · `}
              {doc?.uploaded_at && formatDateTime(doc.uploaded_at)}
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                icon={<Download className="size-3.5" />}
                onClick={() => documentsApi.downloadFile(effectiveId, filename)}
              >
                Download
              </Button>
              <Button variant="secondary" onClick={() => setModalOpen(false)}>
                Close
              </Button>
            </div>
          </div>
        }
      >
        <div className="flex min-h-[28rem] max-h-[80vh] items-center justify-center overflow-auto rounded-lg bg-slate-950/5 p-2">
          {previewUrl && isImage ? (
            <img
              src={previewUrl}
              alt={filename}
              className="max-h-[75vh] w-auto max-w-full rounded object-contain shadow"
            />
          ) : previewUrl && isPdf ? (
            <iframe
              src={previewUrl}
              title="Full PDF Preview"
              className="h-[75vh] w-full rounded border-0"
            />
          ) : (
            <p className="text-sm text-slate-500">Preview not available.</p>
          )}
        </div>
      </Modal>
    </>
  );
}
