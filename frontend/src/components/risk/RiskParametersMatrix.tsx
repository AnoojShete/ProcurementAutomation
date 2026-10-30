import { Fragment, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "@/hooks/useApi";
import { vendorsApi, type RiskParameter, type RiskParameterResult, type VendorRiskParameters } from "@/api/vendors";
import { Section } from "@/components/ui/Card";
import { RiskBadge, StatusDot } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { cn } from "@/lib/cn";

const STATUS_TEXT: Record<string, string> = {
  assessed: "Checked",
  assessed_no_finding: "Checked, nothing found",
  review_pending: "Awaiting review",
  not_assessed: "Couldn't run: left out, weight re-distributed",
  not_applicable: "Doesn't apply",
};

const STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  assessed: "success",
  assessed_no_finding: "success",
  review_pending: "warning",
  not_assessed: "neutral",
  not_applicable: "neutral",
};

// Column headings; the full name is on hover.
const SHORT: Record<string, string> = {
  sanctions: "Sanctions", gst: "GST", bank: "Bank", jurisdiction: "Country", web: "Website", email: "Email",
  breach: "Breaches", certification: "Certification", financial: "Financial", company_age: "Age",
  delivery_sla: "Delivery", feedback: "Feedback", incidents: "Incidents", adverse_media: "News",
};

// One cell: the points a parameter added, out of its weight.
function Cell({ result, max }: { result?: RiskParameterResult; max: number }) {
  if (result?.unverified) {
    // Older scores charged the full weight and have no gap_points.
    const charged = result.gap_points ?? max;
    return (
      <span title={`Missing information: counted as ${charged} of ${max} points until it is filled in. ${result.reason}`}
            className="inline-flex min-w-9 justify-center rounded-sm bg-attention-tint px-1 font-medium tabular text-attention">
        +{charged}!
      </span>
    );
  }
  if (!result || result.status === "not_assessed") {
    return <span className="text-ink-3" title="Couldn't run: left out, its weight goes to the other checks">—</span>;
  }
  if (result.status === "not_applicable") {
    return <span className="text-ink-3" title={result.reason}>n/a</span>;
  }
  const share = max ? result.points / max : 0;
  return (
    <span
      title={`${result.rule_id}: ${result.reason}`}
      className={cn(
        "inline-flex min-w-9 justify-center rounded-sm px-1 tabular",
        result.override ? "bg-danger-50 font-semibold text-danger-700"
          : result.points === 0 ? "text-ink-2"
          : share >= 0.5 ? "bg-warning-50 font-medium text-warning-700" : "text-warning-700",
      )}
    >
      {result.points > 0 ? `+${result.points}` : "0"}
      {result.status === "review_pending" ? "?" : ""}
    </span>
  );
}

function VendorBreakdown({ vendor, parameters }: { vendor: VendorRiskParameters; parameters: RiskParameter[] }) {
  const groups = useMemo(() => {
    const out = new Map<string, RiskParameter[]>();
    parameters.forEach((p) => out.set(p.group, [...(out.get(p.group) ?? []), p]));
    return [...out.entries()];
  }, [parameters]);
  return (
    <div className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-ink">{vendor.name}</span>
        <RiskBadge band={vendor.final_band} ratingStatus={vendor.rating_status} />
        <Link to={`/app/vendors/${vendor.vendor_id}/risk`} className="ml-auto text-13 font-semibold text-brand-600 hover:text-brand-800">
          Full risk scorecard
        </Link>
      </div>
      {vendor.headline && <p className="mt-2 text-13 text-ink-2">{vendor.headline}</p>}
      {vendor.identity_verified === false && (
        <p className="mt-1 text-13 font-medium text-danger-700">
          Identity not verified yet (no verified GSTIN or registration date): not cleared until it is.
        </p>
      )}
      <p className="mt-1 text-caption text-ink-3">
        {vendor.total_points + (vendor.unverified_points ?? 0)} points
        {vendor.unverified_points ? ` (incl. ${vendor.unverified_points} for missing information)` : ""} over the{" "}
        {vendor.checked_max_points ?? 100} points that could be checked
        {vendor.weighted_points != null ? ` = ${vendor.weighted_points}/100` : ""}. Bands: Low 0–24, Medium 25–49, High 50+;
        an override rule decides alone.
      </p>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        {groups.map(([group, params]) => (
          <div key={group}>
            <p className="mb-1 text-13 font-medium text-ink-2">{group}</p>
            <ul className="divide-y divide-rule">
              {params.map((p) => {
                const r = vendor.parameters[p.key];
                const status = r?.status ?? "not_assessed";
                return (
                  <li key={p.key} className="py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-13 text-ink">{p.label}</span>
                      <span className="text-caption text-ink-3">weight {p.max_points}</span>
                      <span className="ml-auto"><Cell result={r} max={p.max_points} /></span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-start gap-2">
                      <StatusDot tone={r?.override ? "danger" : r?.unverified ? "warning" : STATUS_TONE[status] ?? "neutral"}>
                        {r?.override ? "Override: forces High"
                          : r?.unverified ? `Missing information: +${r.gap_points ?? p.max_points} until filled in`
                          : STATUS_TEXT[status] ?? status}
                      </StatusDot>
                      <span className="text-caption text-ink-3">{r?.reason ?? "No result recorded."}</span>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Which parameters were considered for each vendor's band, and what each added. */
export function RiskParametersMatrix() {
  const { data, loading, error, reload } = useApi(() => vendorsApi.riskParameters(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const parameters = data?.parameters ?? [];
  const vendors = data?.vendors ?? [];

  return (
    <Section
      title="Parameters considered"
      subtitle="The 14 checks behind every band, with each one's weight. Missing information about the vendor counts as full risk (+N!); a check that couldn't run on our side (—) is left out and the rest re-weighted to 100. Select a vendor for the reasons."
    >
      {error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : loading && !data ? (
        <Skeleton className="h-48 w-full" />
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-rule">
            <table className="w-full border-collapse text-13">
              <thead className="bg-sheet-sunk text-ink-2">
                <tr>
                  <th className="sticky left-0 z-10 bg-sheet-sunk px-3 py-2 text-left font-medium">Vendor</th>
                  {parameters.map((p) => (
                    <th key={p.key} className="px-1.5 py-2 text-center font-medium" title={`${p.label} (${p.group}): weight ${p.max_points}`}>
                      <span className="block whitespace-nowrap text-caption">{SHORT[p.key] ?? p.label}</span>
                      <span className="block text-caption font-normal text-ink-3">/{p.max_points}</span>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-right font-medium">Points</th>
                  <th className="px-3 py-2 text-right font-medium">Score</th>
                </tr>
              </thead>
              <tbody>
                {vendors.map((v) => (
                  <Fragment key={v.vendor_id}>
                  <tr
                    onClick={() => setSelected(v.vendor_id === selected ? null : v.vendor_id)}
                    className={cn("cursor-pointer border-t border-rule hover:bg-sheet-sunk/60",
                      v.vendor_id === selected && "bg-sheet-sunk")}
                  >
                    <td className={cn("sticky left-0 z-10 px-3 py-2", v.vendor_id === selected ? "bg-sheet-sunk" : "bg-sheet")}>
                      <div className="flex min-w-44 max-w-56 flex-col items-start gap-1">
                        <span className="font-medium leading-tight text-ink">{v.name}</span>
                        <RiskBadge band={v.final_band} ratingStatus={v.rating_status} />
                      </div>
                    </td>
                    {parameters.map((p) => (
                      <td key={p.key} className="px-1.5 py-2 text-center">
                        <Cell result={v.parameters[p.key]} max={p.max_points} />
                      </td>
                    ))}
                    <td className="px-2 py-2 text-right tabular text-ink-2">
                      {v.total_points + (v.unverified_points ?? 0)}/{v.checked_max_points ?? 100}
                    </td>
                    <td className="px-3 py-2 text-right tabular font-medium text-ink">
                      {v.weighted_points ?? "—"}
                    </td>
                  </tr>
                  {v.vendor_id === selected && (
                    <tr className="border-t border-rule bg-sheet">
                      <td colSpan={parameters.length + 3} className="p-0">
                        <div className="sticky left-0 max-w-[calc(100vw-20rem)]">
                          <VendorBreakdown vendor={v} parameters={parameters} />
                        </div>
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-caption text-ink-3">
            +N: points added (out of the weight under each heading) · +N!: nothing on the vendor to verify, counted in
            full · 0: checked, no risk found · ? awaiting review · — couldn't run on our side, left out · n/a doesn't
            apply. Score = points × 100 ÷ points that could be checked. No verified identity = High.
          </p>
        </>
      )}
    </Section>
  );
}
