import { api } from "./client";
import type { DocumentRecord, ReviewCorrectionBody } from "@/types/api";

export const documentsApi = {
  list: (limit = 200) => api.get<DocumentRecord[]>(`/documents/?limit=${limit}`),
  reviewQueue: (limit = 50) => api.get<DocumentRecord[]>(`/documents/review-queue?limit=${limit}`),
  get: (id: string) => api.get<DocumentRecord>(`/documents/${id}`),
  upload: (file: File, uploadedBy: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("uploaded_by", uploadedBy);
    return api.upload<{ document_id: string; status: string }>("/documents/upload", fd);
  },
  submitReview: (id: string, body: ReviewCorrectionBody) =>
    api.post<DocumentRecord>(`/documents/${id}/review`, body),
};
