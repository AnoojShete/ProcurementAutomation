import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { UploadCloud } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { documentsApi } from "@/api/documents";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { DocumentStatusBadge } from "@/components/ui/Badge";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tabs } from "@/components/ui/Tabs";
import { Modal } from "@/components/ui/Modal";
import { FileUploader } from "@/components/ui/FileUploader";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { documentTypeLabel, formatDateTime } from "@/lib/format";
import type { DocumentRecord } from "@/types/api";
import { ApiError } from "@/api/client";

export function DocumentsListPage() {
  usePageHeader("Documents");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: documents, loading, error, reload } = useApi(() => documentsApi.list(200), []);
  const [scope, setScope] = useState<"needs-review" | "all">("all");
  const [uploadOpen, setUploadOpen] = useState(false);

  const rows = useMemo(() => {
    const all = documents ?? [];
    if (scope === "needs-review") return all.filter((d) => d.needs_review);
    return all;
  }, [documents, scope]);

  const columns: Column<DocumentRecord>[] = [
    { key: "filename", header: "Document", render: (d) => <span className="font-medium text-slate-800">{d.original_filename ?? d.id.slice(0, 8)}</span> },
    { key: "type", header: "Type", render: (d) => documentTypeLabel(d.document_type) },
    { key: "vendor", header: "Vendor", render: (d) => d.vendor_name_raw ?? "—" },
    { key: "status", header: "Status", render: (d) => <DocumentStatusBadge status={d.status} needsReview={d.needs_review} /> },
    { key: "confidence", header: "Confidence", render: (d) => <ConfidenceIndicator score={d.overall_confidence} compact /> },
    { key: "uploaded", header: "Uploaded", render: (d) => formatDateTime(d.uploaded_at), sortValue: (d) => d.uploaded_at ?? "" },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "all", label: "All Documents", count: documents?.length },
            { key: "needs-review", label: "Needs Review", count: documents?.filter((d) => d.needs_review).length },
          ]}
          active={scope}
          onChange={(k) => setScope(k as typeof scope)}
        />
        <Button icon={<UploadCloud className="size-4" />} onClick={() => setUploadOpen(true)}>
          Upload Document
        </Button>
      </div>
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(d) => d.id}
            loading={loading}
            onRowClick={(d) => navigate(`/app/documents/${d.id}`)}
            emptyTitle={scope === "needs-review" ? "No documents require review" : "No documents yet"}
            emptyDescription="Uploaded purchase orders, invoices, and quotes will appear here once processed."
          />
        </CardBody>
      </Card>

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} uploadedBy={user!.email} onUploaded={reload} />
    </div>
  );
}

function UploadModal({
  open,
  onClose,
  uploadedBy,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  uploadedBy: string;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const upload = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const res = await documentsApi.upload(file, uploadedBy);
      setSuccess(`Uploaded — processing document ${res.data.document_id.slice(0, 8)}. Extraction runs in the background.`);
      onUploaded();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Upload a document">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-slate-500">
          Purchase order, invoice, or vendor quote (PDF or image). Scanned for malware, then classified and
          field-extracted by the Document Intelligence pipeline.
        </p>
        <FileUploader onFileSelected={setFile} accept=".pdf,.png,.jpg,.jpeg" disabled={uploading} />
        {error && <InlineError message={error} />}
        {success && <InlineSuccess message={success} />}
        <Button loading={uploading} disabled={!file} onClick={upload}>
          Upload
        </Button>
      </div>
    </Modal>
  );
}
