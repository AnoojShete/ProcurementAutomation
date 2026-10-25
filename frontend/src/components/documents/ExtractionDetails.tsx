import { useState } from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Filter } from "lucide-react";
import { documentsApi } from "@/api/documents";
import { useApi } from "@/hooks/useApi";
import { Section } from "@/components/ui/Card";
import { StatusDot } from "@/components/ui/Badge";
import { ConfidenceIndicator } from "@/components/ui/ConfidenceIndicator";
import { InlineError } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import type { DocumentRecord } from "@/types/api";

/** Pipeline stage names as people say them. */
const STAGE_LABEL: Record<string, string> = {
  parsing_agent: "Text reading (pdfplumber / OCR)",
  classification_agent: "Classification",
  field_extraction_agent: "Field extraction",
  layoutlm_crosscheck_agent: "Layout cross-check (LayoutLMv3)",
  vendor_matching_agent: "Vendor match",
  vendor_learning_agent: "Vendor learning",
  currency_agent: "Currency conversion",
  tax_agent: "GST check",
  invoice_matching_agent: "Invoice matching",
  duplicate_detection_agent: "Duplicate check",
  confidence_agent: "Confidence and review decision",
};

const RESULT: Record<string, { tone: "success" | "warning" | "danger" | "neutral"; label: string }> = {
  valid: { tone: "success", label: "Valid" },
  needs_review: { tone: "warning", label: "Needs review" },
  invalid: { tone: "danger", label: "Invalid" },
  skipped: { tone: "neutral", label: "Skipped" },
  skipped_model_unavailable: { tone: "neutral", label: "Skipped: model not installed" },
  skipped_error: { tone: "danger", label: "Skipped after an error" },
};

function fieldLabel(key: string) {
  const s = key.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function show(value: unknown): string {
  if (value == null || value === "") return "—";
  if (Array.isArray(value)) return value.length ? `${value.length} item${value.length > 1 ? "s" : ""}` : "none";
  if (typeof value === "object") {
    try {
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length === 0) return "—";
      return entries.map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(", ");
    } catch {
      return JSON.stringify(value);
    }
  }
  return String(value);
}

function confidenceTier(score: number | undefined): { label: string; color: string } | null {
  if (score == null) return null;
  if (score >= 0.85) return { label: "High", color: "text-success-700 bg-success-50 border-success-200" };
  if (score >= 0.7) return { label: "Medium", color: "text-warning-800 bg-warning-50 border-warning-200" };
  return { label: "Low", color: "text-danger-700 bg-danger-50 border-danger-200" };
}

/** Every field the pipeline extracted, each with its own confidence, and
 * what each pipeline stage concluded (valid / needs review / invalid, with
 * its errors and warnings). */
export function ExtractionDetails({ doc }: { doc: DocumentRecord }) {
  const { data: stages, error } = useApi(() => documentsApi.validation(doc.id), [doc.id, doc.status]);
  const [filterLowConfidence, setFilterLowConfidence] = useState(false);
  const [expandedDiagnostics, setExpandedDiagnostics] = useState(false);

  const confidences = (doc.confidence_scores ?? {}) as Record<string, number | undefined>;

  // Include top-level fields, excluding internal _ prefixed keys and line_items (handled separately)
  const allFields = Object.entries(doc.extracted_fields ?? {}).filter(
    ([k]) => !k.startsWith("_") && k !== "line_items"
  );

  const lowConfidenceFields = allFields.filter(([k]) => {
    const c = confidences[k];
    return c != null && c < 0.7;
  });

  const fields = filterLowConfidence ? lowConfidenceFields : allFields;
  const lineItems = Array.isArray(doc.extracted_fields?.line_items)
    ? (doc.extracted_fields.line_items as Record<string, unknown>[])
    : [];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Section
        title="Every extracted field"
        subtitle={`${allFields.length} field${allFields.length === 1 ? "" : "s"} identified from document content`}
        action={
          allFields.length > 0 && lowConfidenceFields.length > 0 ? (
            <button
              type="button"
              onClick={() => setFilterLowConfidence(!filterLowConfidence)}
              className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
                filterLowConfidence
                  ? "bg-warning-100 text-warning-800 border border-warning-300"
                  : "bg-sheet border border-rule text-ink-2 hover:bg-sheet-sunk"
              }`}
            >
              <Filter className="size-3" />
              {filterLowConfidence ? "Showing low confidence" : `Review needed (${lowConfidenceFields.length})`}
            </button>
          ) : undefined
        }
      >
        {doc.status === "failed" && doc.error_message && (
          <div className="mb-4 rounded-lg border border-danger-200 bg-danger-50 p-3 text-xs text-danger-800">
            <div className="flex items-center gap-2 font-semibold">
              <AlertCircle className="size-4 text-danger-600" />
              Processing Exception Encountered
            </div>
            <p className="mt-1 font-mono">{doc.error_message}</p>
          </div>
        )}

        {fields.length === 0 ? (
          <p className="text-sm text-ink-3">
            {filterLowConfidence ? "No low-confidence fields found." : "No fields were extracted."}
          </p>
        ) : (
          <table className="w-full text-left text-13">
            <thead className="text-ink-3">
              <tr className="border-b border-rule">
                <th className="py-2 pr-3 font-medium">Field</th>
                <th className="py-2 pr-3 font-medium">Value</th>
                <th className="py-2 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {fields.map(([key, value]) => {
                const conf = confidences[key];
                const tier = confidenceTier(conf);
                const isLow = conf != null && conf < 0.7;
                return (
                  <tr key={key} className={`align-top ${isLow ? "bg-warning-50/40" : ""}`}>
                    <td className="py-2 pr-3 text-ink-2 font-medium">
                      <div className="flex items-center gap-1.5">
                        {fieldLabel(key)}
                        {isLow && (
                          <span
                            title="Confidence below review threshold (< 70%)"
                            className="inline-flex size-1.5 rounded-full bg-warning-500"
                          />
                        )}
                      </div>
                    </td>
                    <td className="break-all py-2 pr-3 text-ink">{show(value)}</td>
                    <td className="py-2 whitespace-nowrap">
                      {conf != null ? (
                        <div className="flex items-center gap-1.5">
                          <ConfidenceIndicator score={conf} compact />
                          {tier && (
                            <span className={`rounded border px-1.5 py-0.2 text-[10px] font-medium ${tier.color}`}>
                              {tier.label}
                            </span>
                          )}
                        </div>
                      ) : (
                        <span className="text-ink-3">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}

        {lineItems.length > 0 && !filterLowConfidence && (
          <div className="mt-5 border-t border-rule pt-4">
            <h3 className="mb-2 text-sm font-semibold text-ink">Extracted Line Items ({lineItems.length})</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-13">
                <thead className="text-ink-3">
                  <tr className="border-b border-rule">
                    {Object.keys(lineItems[0]).map((k) => (
                      <th key={k} className="py-1.5 pr-3 font-medium">{fieldLabel(k)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {lineItems.map((item, i) => (
                    <tr key={i}>
                      {Object.keys(lineItems[0]).map((k) => (
                        <td key={k} className="py-1.5 pr-3 text-ink">{show(item[k])}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Section>

      <Section
        title="Validation results"
        subtitle="What each pipeline stage concluded, in order of execution"
        action={
          stages && stages.length > 0 ? (
            <button
              type="button"
              onClick={() => setExpandedDiagnostics(!expandedDiagnostics)}
              className="inline-flex items-center gap-1 text-xs text-accent hover:underline"
            >
              {expandedDiagnostics ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
              {expandedDiagnostics ? "Compact view" : "Diagnostic details"}
            </button>
          ) : undefined
        }
      >
        {error ? (
          <InlineError message={error} />
        ) : !stages ? (
          <Skeleton className="h-40" />
        ) : stages.length === 0 ? (
          <p className="text-sm text-ink-3">
            {doc.status === "pending" || doc.status === "processing"
              ? "The pipeline is still reading this document."
              : "No stage results were recorded for this document."}
          </p>
        ) : (
          <ol className="divide-y divide-rule">
            {stages.map((s) => {
              const r = RESULT[s.validation_status] ?? { tone: "neutral" as const, label: s.validation_status };
              const hasIssues = s.errors.length > 0 || s.warnings.length > 0;
              return (
                <li key={s.agent_name} className="flex flex-col gap-1.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-0 flex-1 text-sm font-medium text-ink">
                      {STAGE_LABEL[s.agent_name] ?? fieldLabel(s.agent_name)}
                    </span>
                    {s.confidence != null && <ConfidenceIndicator score={s.confidence} compact />}
                    <StatusDot tone={r.tone}>{r.label}</StatusDot>
                  </div>

                  {s.errors.map((e) => (
                    <div key={e} className="flex items-start gap-1.5 rounded bg-danger-50 px-2.5 py-1 text-12 text-danger-700">
                      <AlertCircle className="mt-0.5 size-3.5 shrink-0 text-danger-600" />
                      <span>{e}</span>
                    </div>
                  ))}

                  {s.warnings.map((w) => (
                    <div key={w} className="flex items-start gap-1.5 rounded bg-warning-50 px-2.5 py-1 text-12 text-warning-800">
                      <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warning-600" />
                      <span>{w}</span>
                    </div>
                  ))}

                  {expandedDiagnostics && (
                    <div className="flex items-center gap-4 text-11 text-ink-3 pt-0.5">
                      <span>Stage #{s.stage_index}</span>
                      {s.duration_ms != null && <span>Duration: {Math.round(s.duration_ms)} ms</span>}
                      {s.created_at && <span>Executed: {new Date(s.created_at).toLocaleTimeString()}</span>}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </Section>
    </div>
  );
}
