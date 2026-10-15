import { useEffect, useState } from "react";
import { Download, ExternalLink } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Link } from "react-router-dom";
import { documentsApi } from "@/api/documents";
import { documentTypeLabel, formatDateTime } from "@/lib/format";
import type { DocumentRecord } from "@/types/api";
import { DocumentAmount } from "./DocumentAmount";

interface DocumentPreviewModalProps {
  open: boolean;
  onClose: () => void;
  documentId?: string | null;
  document?: DocumentRecord | null;
}

export function DocumentPreviewModal({
  open,
  onClose,
  documentId,
  document,
}: DocumentPreviewModalProps) {
  const effectiveId = document?.id ?? documentId;
  const [doc, setDoc] = useState<DocumentRecord | null>(document ?? null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (document) {
      setDoc(document);
    } else if (effectiveId && open) {
      documentsApi
        .get(effectiveId)
        .then((res) => setDoc(res.data))
        .catch(() => setDoc(null));
    }
  }, [effectiveId, document, open]);

  useEffect(() => {
    if (!open || !effectiveId) {
      setPreviewUrl(null);
      return;
    }

    let active = true;
    let url: string | null = null;
    setLoading(true);

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
        if (active) setPreviewUrl(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      if (url) URL.revokeObjectURL(url);
    };
  }, [open, effectiveId]);

  if (!effectiveId) return null;

  const filename = doc?.original_filename ?? `document-${effectiveId.slice(0, 8)}`;
  const isImage =
    doc?.file_type === "image" ||
    filename.toLowerCase().endsWith(".png") ||
    filename.toLowerCase().endsWith(".jpg") ||
    filename.toLowerCase().endsWith(".jpeg") ||
    filename.toLowerCase().endsWith(".webp");
  const isPdf = doc?.file_type === "pdf" || filename.toLowerCase().endsWith(".pdf");

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={filename}
      size="lg"
      footer={
        <div className="flex w-full items-center justify-between">
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {doc?.document_type && (
              <span className="font-semibold text-slate-700">{documentTypeLabel(doc.document_type)}</span>
            )}
            {doc?.extracted_fields?.total != null && (
              <span>Total: <DocumentAmount doc={doc} /></span>
            )}
            {doc?.uploaded_at && <span>{formatDateTime(doc.uploaded_at)}</span>}
          </div>
          <div className="flex gap-2">
            {doc?.id && (
              <Link
                to={`/app/documents/${doc.id}`}
                className="inline-flex items-center gap-1 rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                <ExternalLink className="size-3.5" /> Full Details
              </Link>
            )}
            <Button
              variant="secondary"
              icon={<Download className="size-3.5" />}
              onClick={() => documentsApi.downloadFile(effectiveId, filename)}
            >
              Download
            </Button>
            <Button variant="secondary" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex min-h-[24rem] max-h-[75vh] items-center justify-center overflow-auto rounded-lg bg-slate-950/5 p-2">
        {loading ? (
          <div className="flex flex-col items-center gap-2 p-8 text-center">
            <Skeleton className="h-48 w-64" />
            <span className="text-xs text-slate-400">Loading document preview...</span>
          </div>
        ) : previewUrl && isImage ? (
          <img
            src={previewUrl}
            alt={filename}
            className="max-h-[70vh] w-auto max-w-full rounded object-contain shadow"
          />
        ) : previewUrl && isPdf ? (
          <iframe
            src={previewUrl}
            title="PDF Preview"
            className="h-[70vh] w-full rounded border-0"
          />
        ) : (
          <p className="text-sm text-slate-500">Preview not available for this document.</p>
        )}
      </div>
    </Modal>
  );
}
