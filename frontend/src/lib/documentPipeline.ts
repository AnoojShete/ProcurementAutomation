import type { DocumentRecord } from "@/types/api";
import type { StageState } from "./lifecycle";

export interface PipelineStep {
  key: string;
  label: string;
  state: StageState;
  /** Every step here is machine work, so "current" means busy (spinner). */
  working?: boolean;
}

/**
 * The backend's real stages (see document-vendor-agent/app/services/pipeline.py):
 * malware scan -> store -> parse/classify/extract/vendor-match (worker,
 * reported as one "processing" status) -> confidence scoring -> review gate.
 * `doc` is undefined while the upload POST itself is in flight.
 */
export function deriveUploadPipeline(doc: DocumentRecord | null, uploading: boolean): PipelineStep[] {
  const status = doc?.status;
  const failed = status === "failed";

  const stageState = (target: "scan" | "processing" | "classified"): StageState => {
    if (failed) return target === "scan" ? "completed" : "failed";
    if (uploading) return "pending";
    if (!doc) return "pending";
    const order = ["pending", "processing", "classified"];
    const currentIdx = order.indexOf(status ?? "pending");
    const targetIdx = target === "scan" ? -1 : target === "processing" ? 1 : 2;
    if (target === "scan") return "completed";
    if (currentIdx > targetIdx) return "completed";
    if (currentIdx === targetIdx) return "completed";
    if (currentIdx === targetIdx - 1) return "current";
    return "pending";
  };

  const steps: PipelineStep[] = [
    { key: "upload", label: "Uploading", state: uploading ? "current" : "completed" },
    { key: "scan", label: "Malware scan", state: uploading ? "pending" : stageState("scan") },
    { key: "extract", label: "Classifying & extracting", state: uploading ? "pending" : stageState("processing") },
    {
      key: "validate",
      label: "Validation",
      state: uploading
        ? "pending"
        : failed
          ? "failed"
          : status === "classified"
            ? "completed"
            : "pending",
    },
    {
      key: "done",
      label: doc?.needs_review ? "Needs review" : "Completed",
      state: uploading
        ? "pending"
        : failed
          ? "blocked"
          : status === "classified"
            ? "completed"
            : "pending",
    },
  ];
  return steps.map((s) => ({ ...s, working: s.state === "current" }));
}

/**
 * Pipeline state derivation for one or more documents being uploaded and processed in batch.
 * Steps move to completed only when all documents finish their processing.
 */
export function deriveMultiUploadPipeline(
  docs: (DocumentRecord | null)[],
  uploading: boolean,
): PipelineStep[] {
  const validDocs = docs.filter((d): d is DocumentRecord => d !== null);
  if (validDocs.length === 0 && !uploading) {
    return [
      { key: "upload", label: "Uploading", state: "pending" },
      { key: "scan", label: "Malware scan", state: "pending" },
      { key: "extract", label: "Classifying & extracting", state: "pending" },
      { key: "validate", label: "Validation", state: "pending" },
      { key: "done", label: "Completed", state: "pending" },
    ];
  }

  if (uploading) {
    return [
      { key: "upload", label: "Uploading", state: "current", working: true },
      { key: "scan", label: "Malware scan", state: "pending" },
      { key: "extract", label: "Classifying & extracting", state: "pending" },
      { key: "validate", label: "Validation", state: "pending" },
      { key: "done", label: "Completed", state: "pending" },
    ];
  }

  const anyProcessing = validDocs.length === 0 || validDocs.some((d) => d.status === "pending" || d.status === "processing");
  const allFailed = validDocs.length > 0 && validDocs.every((d) => d.status === "failed");
  const anyNeedsReview = validDocs.some((d) => d.needs_review);

  const steps: PipelineStep[] = [
    { key: "upload", label: "Uploading", state: "completed" },
    { key: "scan", label: "Malware scan", state: allFailed ? "failed" : "completed" },
    {
      key: "extract",
      label: "Classifying & extracting",
      state: anyProcessing ? "current" : allFailed ? "failed" : "completed",
    },
    {
      key: "validate",
      label: "Validation",
      state: anyProcessing ? "pending" : allFailed ? "failed" : "completed",
    },
    {
      key: "done",
      label: anyNeedsReview ? "Needs review" : "Completed",
      state: anyProcessing ? "pending" : allFailed ? "blocked" : "completed",
    },
  ];

  return steps.map((s) => ({ ...s, working: s.state === "current" }));
}
