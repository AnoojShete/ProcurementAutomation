import { useState } from "react";
import { Link } from "react-router-dom";
import { vendorsApi } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import type { DataNeededItem } from "@/types/api";

// Not typed in: they come from an uploaded document on the full scorecard.
const UPLOADED: Record<string, string> = {
  registration_date: "Upload the incorporation certificate",
  financials: "Upload financials",
};

const FILLABLE: Record<string, { label: string; placeholder: string }> = {
  country: { label: "Country", placeholder: "2-letter code, e.g. IN" },
  gstin: { label: "GSTIN", placeholder: "15 characters, e.g. 27AAPFU0939F1ZV" },
  website: { label: "Website", placeholder: "https://…" },
  contact_email: { label: "Contact email", placeholder: "accounts@vendor.com" },
};

/**
 * Details missing from the vendor record that the risk score is waiting on
 * (the scorecard's `data_needed`). Each costs a third of its check until it
 * is filled in, and the vendor isn't cleared meanwhile. Finance can fill the
 * blanks or confirm the vendor has no GSTIN (asked only for Indian vendors);
 * `onSaved` re-runs the checks. `uploadHref` (the full scorecard) links the
 * items that come from an uploaded document instead.
 * Talks only to document-vendor-agent (/vendors/:id/details, confirm-no-gstin).
 */
export function VendorDataNeeded({
  vendorId,
  items,
  onSaved,
  uploadHref,
}: {
  vendorId: string;
  items: DataNeededItem[];
  onSaved: () => Promise<void> | void;
  uploadHref?: string;
}) {
  const { user } = useAuth();
  const [values, setValues] = useState<Record<string, string>>({});
  const [noGstinReason, setNoGstinReason] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "no_gstin" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canEdit = ["finance", "admin"].includes(user?.role ?? "");
  const fillable = items.filter((i) => i.field in FILLABLE);

  const run = async (kind: "save" | "no_gstin", call: () => Promise<unknown>) => {
    setBusy(kind);
    setError(null);
    try {
      await call();
      setValues({});
      setNoGstinReason(null);
      await onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Request failed.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="rounded-lg border border-attention-soft bg-attention-tint p-3 text-13 text-ink">
      <p className="font-semibold">Data needed</p>
      <p className="mt-0.5 text-ink-2">
        These details aren't in our records, so the checks that need them can't finish. Each adds a third of its
        check's points until it is filled in, and the vendor can't be cleared meanwhile.
      </p>
      <ul className="mt-2 space-y-2">
        {items.map((item) => (
          <li key={item.field}>
            <p>
              {item.message}
              {item.points > 0 && <span className="text-ink-2"> (+{item.points} points meanwhile)</span>}
            </p>
            {canEdit && uploadHref && item.field in UPLOADED && (
              <Link to={uploadHref} className="text-13 font-semibold text-brand-600 hover:text-brand-800">
                {UPLOADED[item.field]}
              </Link>
            )}
            {canEdit && item.field in FILLABLE && (
              <input
                value={values[item.field] ?? ""}
                onChange={(e) => setValues({ ...values, [item.field]: e.target.value })}
                placeholder={FILLABLE[item.field].placeholder}
                aria-label={FILLABLE[item.field].label}
                className="field mt-1 w-80 max-w-full"
              />
            )}
            {canEdit && item.field === "gstin" && (
              noGstinReason === null ? (
                <Button size="sm" variant="ghost" className="ml-2" onClick={() => setNoGstinReason("")}>
                  Vendor has no GSTIN
                </Button>
              ) : (
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <input
                    value={noGstinReason}
                    onChange={(e) => setNoGstinReason(e.target.value)}
                    placeholder="Why, e.g. turnover below the registration threshold"
                    aria-label="Why the vendor has no GSTIN"
                    className="field w-80 max-w-full"
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={!noGstinReason.trim()}
                    loading={busy === "no_gstin"}
                    onClick={() => run("no_gstin", () => vendorsApi.confirmNoGstin(vendorId, noGstinReason.trim()))}
                  >
                    Confirm no GSTIN
                  </Button>
                </div>
              )
            )}
          </li>
        ))}
      </ul>
      {canEdit && fillable.length > 0 && (
        <Button
          size="sm"
          className="mt-3"
          disabled={!fillable.some((i) => values[i.field]?.trim())}
          loading={busy === "save"}
          onClick={() => run("save", () => vendorsApi.fillDetails(vendorId, values))}
        >
          Save and re-check
        </Button>
      )}
      {!canEdit && fillable.length > 0 && (
        <p className="mt-2 text-ink-2">Finance can fill these in from this page.</p>
      )}
      {error && <InlineError message={error} />}
    </div>
  );
}
