import { api } from "./client";

export interface KafkaEvent {
  seq: number;
  topic: string;
  partition: number;
  offset: number;
  timestamp: string | null;
  event_type: string;
  source_service: string | null;
  correlation_id: string | null;
  message: string;
  fields: Record<string, unknown>;
}

export interface EventLog {
  status: { connected: boolean; error: string | null; topics?: string[]; buffered?: number };
  events: KafkaEvent[];
  latest_seq: number;
}

export interface EventFilters {
  topic?: string;
  correlation_id?: string;
  since_hours?: number;
  q?: string;
}

/** A dead-lettered event, summarised (never the full payload). */
export interface FailedEvent {
  id: string;
  consumer: string;
  topic: string;
  event_id: string | null;
  error: string;
  attempts: number;
  failed_at: string;
  message: string;
  correlation_id: string | null;
  fields: Record<string, unknown>;
}

export type DropStage =
  | "processing" | "failed" | "review" | "stopped" | "approval" | "rejected" | "contract" | "signature" | "signed";

export interface DroppedFile {
  document_id: string;
  original_filename: string | null;
  document_status: string;
  document_type: string | null;
  uploaded_at: string | null;
  total: number | null;
  currency: string | null;
  request_id: string | null;
  request_status: string | null;
  contract_id: string | null;
  contract_status: string | null;
  esign_provider_ref: string | null;
  stage: DropStage;
  stage_label: string;
}

export interface InboxStatus {
  enabled: boolean;
  host_path: string;
  poll_seconds: number;
  uploader: string;
  folder: {
    mounted: boolean;
    /** Files in input/ (and being uploaded). */
    waiting: string[];
    /** Uploaded, waiting for the pipeline before moving to processed/ or failed/. */
    in_pipeline?: { document_id: string; name: string }[];
    processed_count?: number;
    failed_count?: number;
    failed: { name: string; reason: string; error_log?: string; document_id?: string | null; failed_at?: string | null }[];
    paths?: { input: string; processed: string; failed: string };
  };
  drops: DroppedFile[];
}

export interface StorageStatus {
  connected: boolean;
  error: string | null;
  endpoint: string;
  bucket: string;
  console_url: string;
  buckets?: string[];
  object_count?: number;
  total_bytes?: number;
  count_capped?: boolean;
  recent?: { key: string; size: number; last_modified: string | null }[];
}

export interface EsignStatus {
  docusign: {
    configured: boolean;
    connected: boolean;
    environment: string;
    base_url: string;
    account_id: string | null;
    error: string | null;
    consent_url: string | null;
    connect_webhook: boolean;
    poll_seconds: number;
  };
  documenso: { configured: boolean };
  auto_send: { enabled: boolean; provider: string; signer_email: string | null };
  envelopes: {
    contract_id: string;
    status: string;
    esign_provider_ref: string;
    signer_email: string | null;
    sent_at: string | null;
    signed_at: string | null;
    automatic: boolean | null;
    live: boolean;
  }[];
}

/** Admin control panel: the drop-folder automation and its connections. */
export const controlPanelApi = {
  events: (after = 0, filters: EventFilters = {}) => {
    const qs = new URLSearchParams({ after: String(after) });
    Object.entries(filters).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
    return api.get<EventLog>(`/admin/control-panel/events?${qs}`);
  },
  failedEvents: () => api.get<FailedEvent[]>("/admin/control-panel/failed-events"),
  inbox: () => api.get<InboxStatus>("/admin/control-panel/inbox"),
  storage: () => api.get<StorageStatus>("/admin/control-panel/storage"),
  esign: () => api.get<EsignStatus>("/contracts/esign/status"),
};
