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
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Every field the pipeline extracted, each with its own confidence, and
 * what each pipeline stage concluded (valid / needs review / invalid, with
 * its errors and warnings). Read-only: corrections are made in the
 * Extracted Fields form above. */
export function ExtractionDetails({ doc }: { doc: DocumentRecord }) {
  const { data: stages, error } = useApi(() => documentsApi.validation(doc.id), [doc.id, doc.status]);
  // Nested diagnostics (e.g. the LayoutLMv3 cross-check) are covered by
  // the stage results; the table lists the fields themselves.
  const fields = Object.entries(doc.extracted_fields ?? {}).filter(
    ([k, v]) => !k.startsWith("_") && (v == null || typeof v !== "object" || Array.isArray(v)),
  );
  const confidences = (doc.confidence_scores ?? {}) as Record<string, number | undefined>;
  const lineItems = Array.isArray(doc.extracted_fields?.line_items) ? (doc.extracted_fields.line_items as Record<string, unknown>[]) : [];

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <Section title="Every extracted field" subtitle={`${fields.length} field${fields.length === 1 ? "" : "s"} read from the document`}>
        {doc.status === "failed" && doc.error_message && (
          <div className="mb-3"><InlineError message={`Processing failed: ${doc.error_message}`} /></div>
        )}
        {fields.length === 0 ? (
          <p className="text-sm text-ink-3">No fields were extracted.</p>
        ) : (
          <table className="w-full text-left text-13">
            <thead className="text-ink-3">
              <tr className="border-b border-rule">
                <th className="py-1.5 pr-3 font-medium">Field</th>
                <th className="py-1.5 pr-3 font-medium">Value</th>
                <th className="py-1.5 font-medium">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {fields.map(([key, value]) => (
                <tr key={key} className="align-top">
                  <td className="py-1.5 pr-3 text-ink-2">{fieldLabel(key)}</td>
                  <td className="break-all py-1.5 pr-3 font-medium text-ink">{show(value)}</td>
                  <td className="py-1.5">
                    {confidences[key] != null ? <ConfidenceIndicator score={confidences[key]!} compact /> : <span className="text-ink-3">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {lineItems.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-1.5 text-sm font-semibold text-ink">Line items</h3>
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
        )}
      </Section>

      <Section title="Validation results" subtitle="What each pipeline stage concluded, in order">
        {error ? (
          <InlineError message={error} />
        ) : !stages ? (
          <Skeleton className="h-40" />
        ) : stages.length === 0 ? (
          <p className="text-sm text-ink-3">
            {doc.status === "pending" || doc.status === "processing" ? "The pipeline is still reading this document." : "No stage results were recorded for this document."}
          </p>
        ) : (
          <ol className="divide-y divide-rule">
            {stages.map((s) => {
              const r = RESULT[s.validation_status] ?? { tone: "neutral" as const, label: s.validation_status };
              return (
                <li key={s.agent_name} className="flex flex-col gap-1 py-2">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="min-w-0 flex-1 text-sm font-medium text-ink">{STAGE_LABEL[s.agent_name] ?? fieldLabel(s.agent_name)}</span>
                    {s.confidence != null && <ConfidenceIndicator score={s.confidence} compact />}
                    <StatusDot tone={r.tone}>{r.label}</StatusDot>
                  </div>
                  {s.errors.map((e) => (
                    <p key={e} className="text-13 text-danger-600">{e}</p>
                  ))}
                  {s.warnings.map((w) => (
                    <p key={w} className="text-13 text-warning-700">{w}</p>
                  ))}
                  {s.duration_ms != null && <p className="text-13 text-ink-3">{Math.round(s.duration_ms)} ms</p>}
                </li>
              );
            })}
          </ol>
        )}
      </Section>
    </div>
  );
}
