import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { FileText, Loader2, Upload, X } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { documentsApi } from "@/api/documents";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { DocumentStatusBadge, StatusDot } from "@/components/ui/Badge";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { ErrorState } from "@/components/ui/ErrorState";
import { Tabs } from "@/components/ui/Tabs";
import { Modal } from "@/components/ui/Modal";
import { FileUploader } from "@/components/ui/FileUploader";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { documentTypeLabel, formatDateTime } from "@/lib/format";
import type { BatchUploadResult, DocumentRecord } from "@/types/api";
import { ApiError } from "@/api/client";

export function DocumentsListPage() {
  usePageHeader("Documents");
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
    {
      key: "filename",
      header: "Document",
      render: (d) => (
        <span className="block max-w-[22rem] truncate font-medium text-slate-900" title={d.original_filename ?? undefined}>
          {d.original_filename ?? d.id.slice(0, 8)}
        </span>
      ),
    },
    { key: "type", header: "Type", render: (d) => documentTypeLabel(d.document_type) },
    { key: "vendor", header: "Vendor", render: (d) => <span className="block max-w-[14rem] truncate">{d.vendor_name_raw ?? "—"}</span> },
    { key: "status", header: "Status", render: (d) => <DocumentStatusBadge status={d.status} needsReview={d.needs_review} /> },
    { key: "confidence", header: "Confidence", render: (d) => <ConfidenceIndicator score={d.overall_confidence} compact /> },
    {
      key: "uploaded",
      header: "Uploaded",
      className: "whitespace-nowrap",
      render: (d) => <span className="text-slate-600">{formatDateTime(d.uploaded_at)}</span>,
      sortValue: (d) => d.uploaded_at ?? "",
    },
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
        <Button icon={<Upload className="size-4" />} onClick={() => setUploadOpen(true)}>
          Upload documents
        </Button>
      </div>
      <Card>
        <CardBody className="p-2 sm:p-0">
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

      <UploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} onUploaded={reload} />
    </div>
  );
}

const MAX_FILES = 20;
const MAX_FILE_BYTES = 25 * 1024 * 1024;
const TERMINAL = new Set(["classified", "failed"]);

type QueueItem = {
  key: string;
  file: File;
  documentId?: string;
  status: "queued" | "rejected" | "pending" | "processing" | "classified" | "failed";
  detail?: string;
  needsReview?: boolean;
};

function formatBytes(n: number) {
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function UploadModal({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  onUploaded: () => void;
}) {
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const tracking = queue.filter((q) => q.documentId && !TERMINAL.has(q.status));

  const addFiles = (files: File[]) => {
    setError(null);
    setQueue((prev) => {
      const next = [...prev];
      for (const file of files) {
        if (next.some((q) => q.file.name === file.name && q.file.size === file.size)) continue;
        if (next.length >= MAX_FILES) {
          setError(`Up to ${MAX_FILES} files per upload.`);
          break;
        }
        const problem = file.size === 0 ? "File is empty" : file.size > MAX_FILE_BYTES ? "Larger than 25 MB" : undefined;
        next.push({
          key: `${file.name}-${file.size}-${file.lastModified}`,
          file,
          status: problem ? "rejected" : "queued",
          detail: problem,
        });
      }
      return next;
    });
  };

  const upload = async () => {
    const pending = queue.filter((q) => q.status === "queued");
    if (!pending.length) return;
    setUploading(true);
    setError(null);
    setSubmitted(true);
    const apply = (results: BatchUploadResult[]) => {
      setQueue((prev) =>
        prev.map((q) => {
          const i = pending.indexOf(q);
          if (i < 0) return q;
          const r = results[i];
          if (!r) return q;
          return r.document_id
            ? { ...q, documentId: r.document_id, status: "pending" }
            : { ...q, status: "rejected", detail: r.error };
        }),
      );
    };
    try {
      const res = await documentsApi.uploadBatch(pending.map((q) => q.file));
      apply(res.data);
      onUploaded();
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { data?: BatchUploadResult[] } | undefined) : undefined;
      if (body?.data) apply(body.data);
      else {
        setError(e instanceof ApiError ? e.message : "Upload failed.");
        setSubmitted(false);
      }
    } finally {
      setUploading(false);
    }
  };

  // Follow each accepted document through the pipeline. The worker handles
  // several at once, so rows finish in whatever order they're done.
  useEffect(() => {
    if (!tracking.length) return;
    const timer = setInterval(async () => {
      try {
        const res = await documentsApi.list(200);
        const byId = new Map(res.data.map((d) => [d.id, d]));
        setQueue((prev) =>
          prev.map((q) => {
            const d = q.documentId ? byId.get(q.documentId) : undefined;
            if (!d) return q;
            return { ...q, status: d.status as QueueItem["status"], needsReview: d.needs_review, detail: d.error_message ?? undefined };
          }),
        );
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [tracking.length]);

  const wasTracking = useRef(false);
  useEffect(() => {
    if (tracking.length) wasTracking.current = true;
    else if (wasTracking.current) {
      wasTracking.current = false;
      onUploaded();
    }
  }, [tracking.length, onUploaded]);

  const close = () => {
    if (uploading) return;
    setQueue([]);
    setError(null);
    setSubmitted(false);
    onClose();
  };

  const counts = {
    done: queue.filter((q) => q.status === "classified").length,
    failed: queue.filter((q) => q.status === "failed" || q.status === "rejected").length,
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Upload documents"
      size="lg"
      footer={
        submitted ? (
          <Button variant="secondary" onClick={close} disabled={uploading}>
            {tracking.length ? "Close — processing continues" : "Done"}
          </Button>
        ) : (
          <>
            <Button variant="secondary" onClick={close}>
              Cancel
            </Button>
            <Button loading={uploading} disabled={!queue.some((q) => q.status === "queued")} onClick={upload}>
              Upload {queue.filter((q) => q.status === "queued").length || ""} file
              {queue.filter((q) => q.status === "queued").length === 1 ? "" : "s"}
            </Button>
          </>
        )
      }
    >
      <div className="flex flex-col gap-3">
        {!submitted && (
          <>
            <p className="text-13 text-slate-600">
              Each file is scanned for malware, then classified and field-extracted. Files are processed in
              parallel. Up to {MAX_FILES} files, 25 MB each.
            </p>
            <FileUploader multiple onFilesSelected={addFiles} accept=".pdf,.png,.jpg,.jpeg" disabled={uploading} />
          </>
        )}
        {error && <InlineError message={error} />}
        {queue.length > 0 && (
          <div className="rounded-md border border-surface-border">
            <div className="flex items-center justify-between border-b border-surface-border bg-surface-subtle px-3 py-1.5 text-xs text-slate-600">
              <span>
                {queue.length} file{queue.length === 1 ? "" : "s"}
              </span>
              {submitted && (
                <span className="tabular">
                  {counts.done} processed · {tracking.length} in progress · {counts.failed} failed
                </span>
              )}
            </div>
            <ul className="max-h-72 divide-y divide-surface-border overflow-y-auto">
              {queue.map((q) => (
                <li key={q.key} className="flex items-center gap-3 px-3 py-2 text-13">
                  <FileText className="size-4 shrink-0 text-slate-400" strokeWidth={1.75} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-slate-900">{q.file.name}</p>
                    {q.detail && <p className="truncate text-xs text-danger-600">{q.detail}</p>}
                  </div>
                  <span className="shrink-0 text-xs text-slate-500 tabular">{formatBytes(q.file.size)}</span>
                  <span className="w-28 shrink-0 text-right">
                    <QueueStatus item={q} />
                  </span>
                  {!submitted && (
                    <button
                      onClick={() => setQueue((prev) => prev.filter((x) => x !== q))}
                      className="rounded p-0.5 text-slate-400 hover:bg-surface-muted hover:text-slate-700"
                      aria-label={`Remove ${q.file.name}`}
                    >
                      <X className="size-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  );
}

function QueueStatus({ item }: { item: QueueItem }) {
  switch (item.status) {
    case "queued":
      return <span className="text-xs text-slate-500">Ready</span>;
    case "rejected":
      return <StatusDot tone="danger">Rejected</StatusDot>;
    case "pending":
    case "processing":
      return (
        <span className="inline-flex items-center gap-1.5 text-13 text-slate-600">
          <Loader2 className="size-3.5 animate-spin" />
          {item.status === "pending" ? "Queued" : "Processing"}
        </span>
      );
    case "classified":
      return item.needsReview ? <StatusDot tone="warning">Needs review</StatusDot> : <StatusDot tone="success">Processed</StatusDot>;
    case "failed":
      return <StatusDot tone="danger">Failed</StatusDot>;
  }
}
