import { Link } from "react-router-dom";
import { Download, ExternalLink, FileText } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { InlineError } from "@/components/ui/ErrorState";
import { DocumentStatusBadge } from "@/components/ui/Badge";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { ExtractionDetails } from "@/components/documents/ExtractionDetails";
import { useApi } from "@/hooks/useApi";
import { documentsApi } from "@/api/documents";
import { formatDateTime } from "@/lib/format";

interface DocumentInspectionModalProps {
  documentId: string | null;
  onClose: () => void;
}

export function DocumentInspectionModal({ documentId, onClose }: DocumentInspectionModalProps) {
  const { data: doc, error, loading } = useApi(
    () => (documentId ? documentsApi.get(documentId) : Promise.resolve({ data: null, meta: {} })),
    [documentId],
  );

  if (!documentId) return null;

  return (
    <Modal
      open={!!documentId}
      onClose={onClose}
      title={doc ? `Document Extraction: ${doc.original_filename ?? doc.id.slice(0, 8)}` : "Document Extraction"}
      size="xl"
      footer={
        <div className="flex w-full items-center justify-between">
          {doc && (
            <div className="flex items-center gap-3">
              <Button
                variant="secondary"
                size="sm"
                icon={<Download className="size-3.5" />}
                onClick={() => documentsApi.downloadFile(doc.id, doc.original_filename ?? "document")}
              >
                Download File
              </Button>
              <Link
                to={`/app/documents/${doc.id}`}
                className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
              >
                Go to Document Detail <ExternalLink className="size-3" />
              </Link>
            </div>
          )}
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      {loading && !doc ? (
        <div className="flex flex-col gap-4 p-4">
          <Skeleton className="h-10 w-3/4" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : error ? (
        <div className="p-4">
          <InlineError message={`Couldn't load document extraction: ${error}`} />
        </div>
      ) : !doc ? (
        <p className="p-4 text-sm text-ink-3">Document not found.</p>
      ) : (
        <div className="flex flex-col gap-5">
          {/* Top summary strip */}
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-rule bg-sheet-sunk p-3 text-13">
            <div className="flex items-center gap-2">
              <FileText className="size-4 text-accent" />
              <span className="font-semibold text-ink">{doc.original_filename ?? doc.id}</span>
              <DocumentStatusBadge status={doc.status} needsReview={doc.needs_review} />
            </div>
            <div className="flex items-center gap-4 text-ink-2">
              {doc.document_type && (
                <span className="capitalize font-medium">Type: {doc.document_type}</span>
              )}
              {doc.overall_confidence != null && (
                <div className="flex items-center gap-1.5">
                  <span className="text-ink-3">Overall Confidence:</span>
                  <ConfidenceIndicator score={doc.overall_confidence} />
                </div>
              )}
              {doc.uploaded_at && (
                <span className="text-ink-3">Received: {formatDateTime(doc.uploaded_at)}</span>
              )}
            </div>
          </div>

          {/* Full extraction and validation breakdown */}
          <ExtractionDetails doc={doc} />
        </div>
      )}
    </Modal>
  );
}
