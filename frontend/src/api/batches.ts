/**
 * Batch upload API client (Prompt 11 Section 4).
 */
import { api, downloadFile } from "./client";

export interface BatchFileItem {
  client_file_id: string;
  client_relative_path: string;
  filename: string;
  file_size_bytes: number;
}

export interface CreateBatchRequest {
  total_files: number;
  files: BatchFileItem[];
  metadata?: Record<string, any>;
}

export interface CreateBatchResponse {
  batch_id: string;
  status: string;
  total_files: number;
  created_at: string;
}

export interface BatchFileDetail {
  id: string;
  client_file_id: string;
  client_relative_path: string;
  filename: string;
  file_size_bytes: number;
  sha256_hash?: string;
  status: "queued" | "uploading" | "completed" | "failed" | "cancelled";
  document_id?: string;
  error_code?: string;
  error_detail?: string;
  retry_count: number;
  updated_at?: string;
}

export interface BatchSummary {
  batch_id: string;
  user_id: string;
  status: "in_progress" | "completed" | "cancelled";
  total_files: number;
  processed_files: number;
  failed_files: number;
  cancelled_files: number;
  created_at?: string;
  completed_at?: string;
  metadata?: Record<string, any>;
  files: BatchFileDetail[];
}

export const batchesApi = {
  createBatch: async (payload: CreateBatchRequest): Promise<CreateBatchResponse> => {
    const res = await api.post<CreateBatchResponse>("/documents/batches", payload);
    return res.data;
  },

  getBatch: async (batchId: string): Promise<BatchSummary> => {
    const res = await api.get<BatchSummary>(`/documents/batches/${batchId}`);
    return res.data;
  },

  cancelBatch: async (batchId: string): Promise<{ batch_id: string; status: string; cancelled_files: number }> => {
    const res = await api.post<{ batch_id: string; status: string; cancelled_files: number }>(
      `/documents/batches/${batchId}/cancel`,
      {},
    );
    return res.data;
  },

  retryFailed: async (batchId: string): Promise<{ batch_id: string; status: string; retried_files: number }> => {
    const res = await api.post<{ batch_id: string; status: string; retried_files: number }>(
      `/documents/batches/${batchId}/retry-failed`,
      {},
    );
    return res.data;
  },

  downloadReportCsv: async (batchId: string): Promise<void> => {
    await downloadFile(`/documents/batches/${batchId}/report.csv`, `batch_${batchId.slice(0, 8)}_report.csv`);
  },

  uploadBatchFile: async (
    file: File,
    batchId: string,
    clientFileId: string,
    clientRelativePath: string,
    onProgress?: (pct: number) => void,
  ): Promise<{ document_id?: string; status: string; is_likely_duplicate?: boolean; duplicate_of_document_id?: string }> => {
    const formData = new FormData();
    formData.append("file", file, file.name);

    const queryParams = new URLSearchParams({
      batch_id: batchId,
      client_file_id: clientFileId,
      client_relative_path: clientRelativePath,
    });

    const res = await api.upload<{ document_id?: string; status: string; is_likely_duplicate?: boolean; duplicate_of_document_id?: string }>(
      `/documents/upload?${queryParams.toString()}`,
      formData,
    );
    if (onProgress) onProgress(100);
    return res.data;
  },
};
