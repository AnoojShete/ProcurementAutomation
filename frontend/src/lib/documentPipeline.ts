import type { DocumentRecord } from "@/types/api";
import type { StageState } from "./lifecycle";

export interface PipelineStep {
  key: string;
  label: string;
  state: StageState;
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
    { key: "scan", label: "Malware Scan", state: uploading ? "pending" : stageState("scan") },
    { key: "extract", label: "Classifying & Extracting", state: uploading ? "pending" : stageState("processing") },
    {
      key: "validate",
      label: "Validation",
      state: uploading
        ? "pending"
        : failed
          ? "failed"
          : status === "classified"
            ? doc?.needs_review
              ? "current"
              : "completed"
            : "pending",
    },
    {
      key: "done",
      label: doc?.needs_review ? "Needs Review" : "Completed",
      state: uploading ? "pending" : failed ? "blocked" : status === "classified" && !doc?.needs_review ? "completed" : "pending",
    },
  ];
  return steps;
}
