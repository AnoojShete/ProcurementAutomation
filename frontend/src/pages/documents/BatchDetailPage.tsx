import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Download, FileText, Loader2, RefreshCw, XCircle } from "lucide-react";
import { batchesApi, type BatchSummary } from "@/api/batches";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { usePageHeader } from "@/hooks/usePageTitle";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function BatchDetailPage() {
  usePageHeader("Upload Batch Details");
  const { batchId } = useParams<{ batchId: string }>();

  const [batch, setBatch] = useState<BatchSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchBatch = async () => {
    if (!batchId) return;
    try {
      const data = await batchesApi.getBatch(batchId);
      setBatch(data);
      setError(null);
    } catch (err: any) {
      setError(err?.message || "Failed to load batch details");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBatch();
  }, [batchId]);

  // Polling while batch is in progress
  useEffect(() => {
    if (!batch || batch.status !== "in_progress") return;
    const interval = setInterval(fetchBatch, 2500);
    return () => clearInterval(interval);
  }, [batch?.status, batchId]);

  const handleCancel = async () => {
    if (!batchId) return;
    setActionLoading(true);
    try {
      await batchesApi.cancelBatch(batchId);
      await fetchBatch();
    } catch (err: any) {
      alert(err?.message || "Failed to cancel batch");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRetryFailed = async () => {
    if (!batchId) return;
    setActionLoading(true);
    try {
      await batchesApi.retryFailed(batchId);
      await fetchBatch();
    } catch (err: any) {
      alert(err?.message || "Failed to retry failed files");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDownloadCsv = async () => {
    if (!batchId) return;
    try {
      await batchesApi.downloadReportCsv(batchId);
    } catch (err: any) {
      alert(err?.message || "Failed to download CSV report");
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-8 animate-spin text-brand-600" />
      </div>
    );
  }

  if (error || !batch) {
    return (
      <div className="rounded-md bg-red-50 p-6 text-red-700">
        <p className="font-semibold">Error</p>
        <p className="text-sm">{error || "Batch not found"}</p>
        <Link to="/app/documents" className="mt-4 inline-block text-sm font-medium underline">
          Back to Documents
        </Link>
      </div>
    );
  }

  const finishedCount = batch.processed_files + batch.failed_files + batch.cancelled_files;
  const pct = batch.total_files > 0 ? Math.round((finishedCount / batch.total_files) * 100) : 0;

  const getTone = (status: string): "neutral" | "success" | "warning" | "danger" | "brand" => {
    if (status === "completed") return "success";
    if (status === "failed") return "danger";
    if (status === "cancelled") return "warning";
    if (status === "uploading") return "brand";
    return "neutral";
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link
            to="/app/documents"
            className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft className="size-4" /> Documents
          </Link>
          <span className="text-slate-300">/</span>
          <span className="font-mono text-sm text-slate-600">Batch {batch.batch_id.slice(0, 8)}</span>
        </div>

        <div className="flex items-center gap-2">
          {batch.failed_files > 0 && batch.status !== "in_progress" && (
            <Button variant="secondary" size="sm" onClick={handleRetryFailed} disabled={actionLoading}>
              <RefreshCw className="mr-1.5 size-3.5" />
              Retry Failed ({batch.failed_files})
            </Button>
          )}

          {batch.status === "in_progress" && (
            <Button variant="destructive" size="sm" onClick={handleCancel} disabled={actionLoading}>
              <XCircle className="mr-1.5 size-3.5" />
              Cancel Batch
            </Button>
          )}

          <Button variant="secondary" size="sm" onClick={handleDownloadCsv}>
            <Download className="mr-1.5 size-3.5" />
            Download CSV Report
          </Button>
        </div>
      </div>

      {/* Batch Overview Card */}
      <div className="rounded-lg border border-surface-border bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-semibold text-slate-900">Upload Batch Summary</h2>
              <Badge tone={getTone(batch.status)}>
                {batch.status.replace("_", " ")}
              </Badge>
            </div>
            <p className="text-xs text-slate-500">
              Started by {batch.user_id} on {batch.created_at ? new Date(batch.created_at).toLocaleString() : "—"}
            </p>
          </div>

          <div className="flex items-center gap-6 text-sm">
            <div>
              <span className="text-xs text-slate-500">Total Files</span>
              <p className="font-semibold text-slate-900">{batch.total_files}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500">Processed</span>
              <p className="font-semibold text-emerald-600">{batch.processed_files}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500">Failed</span>
              <p className="font-semibold text-rose-600">{batch.failed_files}</p>
            </div>
            <div>
              <span className="text-xs text-slate-500">Cancelled</span>
              <p className="font-semibold text-amber-600">{batch.cancelled_files}</p>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="pt-4">
          <div className="flex items-center justify-between text-xs text-slate-600 mb-1">
            <span>Overall Progress</span>
            <span className="font-mono font-medium">{pct}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
            <div
              className={`h-full transition-all duration-300 ${
                batch.status === "completed" ? "bg-emerald-500" : batch.status === "cancelled" ? "bg-amber-500" : "bg-brand-600"
              }`}
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Files List Table */}
      <div className="overflow-hidden rounded-lg border border-surface-border bg-white shadow-sm">
        <div className="border-b border-surface-border bg-slate-50 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800">Files in Batch ({batch.files.length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-slate-600">
            <thead className="border-b border-slate-200 bg-slate-50/50 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-2.5">File / Path</th>
                <th className="px-4 py-2.5">Size</th>
                <th className="px-4 py-2.5">Status</th>
                <th className="px-4 py-2.5">Document</th>
                <th className="px-4 py-2.5">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {batch.files.map((file) => (
                <tr key={file.id} className="hover:bg-slate-50/50">
                  <td className="px-4 py-3">
                    <div className="flex items-start gap-2">
                      <FileText className="mt-0.5 size-4 text-slate-400 shrink-0" />
                      <div>
                        <p className="font-medium text-slate-900">{file.filename}</p>
                        {file.client_relative_path && file.client_relative_path !== file.filename && (
                          <p className="text-xs text-slate-400 font-mono">{file.client_relative_path}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                    {formatBytes(file.file_size_bytes)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <Badge tone={getTone(file.status)}>
                      {file.status}
                    </Badge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs">
                    {file.document_id ? (
                      <Link
                        to={`/app/documents/${file.document_id}`}
                        className="font-mono text-brand-600 hover:underline"
                      >
                        {file.document_id.slice(0, 8)}...
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {file.error_detail ? (
                      <span className="text-rose-600" title={file.error_detail}>
                        {file.error_code ? `[${file.error_code}] ` : ""}
                        {file.error_detail.length > 60
                          ? `${file.error_detail.slice(0, 60)}...`
                          : file.error_detail}
                      </span>
                    ) : file.status === "completed" ? (
                      <span className="inline-flex items-center text-emerald-600 gap-1">
                        <CheckCircle2 className="size-3.5" /> Uploaded
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
