import { Link, useNavigate, useParams } from "react-router-dom";
import { Lock } from "lucide-react";
import { sourcingApi } from "@/api/sourcing";
import { AwardButton, SourcingActions } from "@/components/approvals/SourcingActions";
import { StatusDot } from "@/components/ui/Badge";
import { Section } from "@/components/ui/Card";
import { DocketHeader } from "@/components/ui/DocketHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { RFQ_STATUS } from "@/pages/sourcing/RfqListPage";
import type { RfqCriterion } from "@/types/api";

const CRITERION: Record<RfqCriterion, string> = {
  price: "Price", lead_time: "Lead time", warranty: "Warranty", support: "Support", vendor_risk: "Vendor risk", delivery_record: "Delivery record",
};

/** One RFQ's home page: invitations, quotes, the comparison and its actions. */
export function RfqDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canRun = user?.role === "finance" || user?.role === "admin";
  const { data: rfq, loading, error, reload } = useApi(() => sourcingApi.get(id!), [id]);
  usePageHeader(rfq ? rfq.reference : "RFQ", "Sourcing");

  if (loading && !rfq) return <Skeleton className="h-96" />;
  if (error || !rfq) return <ErrorState message={error ?? "RFQ not found."} onRetry={reload} />;

  const ranked = rfq.comparison?.ranked ?? [];
  const best = ranked[0];
  const cheapest = ranked.length ? Math.min(...ranked.map((r) => r.total_inr)) : null;
  const invited = rfq.invitations.filter((i) => i.round === rfq.round);
  const weights = Object.entries(rfq.criteria).filter(([, w]) => (w ?? 0) > 0) as [RfqCriterion, number][];

  return (
    <div className="flex flex-col gap-6">
      <DocketHeader
        reference={<span className="font-mono text-13 text-ink-3">{rfq.reference}</span>}
        title={rfq.title}
        status={<StatusDot tone={RFQ_STATUS[rfq.status].tone}>{RFQ_STATUS[rfq.status].label}</StatusDot>}
        meta={<span>{rfq.department} · {titleCase(rfq.request_type)} · round {rfq.round} · quotes due {formatDateTime(rfq.deadline)}{rfq.sealed ? " · sealed" : ""}</span>}
      />

      <LedgerStrip cols={4} label="RFQ figures">
        <MetricCard label="Quotes in" value={`${invited.filter((i) => i.responded_at).length} of ${invited.length}`} hint={`round ${rfq.round}`} />
        <MetricCard label="Lowest total" value={rfq.sealed_now ? "Sealed" : cheapest != null ? formatCurrency(cheapest) : "—"} />
        <MetricCard label="Best overall" value={rfq.sealed_now ? "Sealed" : best?.vendor_name ?? "—"} hint={best ? `score ${best.total_score.toFixed(2)}` : undefined} />
        <MetricCard label="Awarded" value={rfq.awarded_request_id ? "Yes" : "Not yet"}
          hint={rfq.awarded_request_id ? <Link className="text-accent hover:underline" to={`/app/requests/${rfq.awarded_request_id}`}>PR-{rfq.awarded_request_id.slice(0, 8)}</Link> : undefined} />
      </LedgerStrip>

      {canRun && <SourcingActions rfq={rfq} onChanged={reload} />}

      <Section title="Comparison" subtitle={rfq.sealed_now
        ? undefined
        : `Each criterion scored 0–1 among this round's quotes, weighted ${weights.map(([k, w]) => `${CRITERION[k].toLowerCase()} ${Math.round(w * 100)}%`).join(", ")}. Unknown counts as average.`}>
        {rfq.sealed_now ? (
          <p className="flex items-center gap-2 text-13 text-ink-2"><Lock className="size-4" aria-hidden="true" />
            Sealed until {formatDateTime(rfq.deadline)}: amounts stay hidden from everyone, including admins. Who has quoted is shown below.</p>
        ) : ranked.length === 0 ? (
          <p className="text-13 text-ink-3">No quotes in this round.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-13">
              <thead>
                <tr className="border-b border-rule text-left text-ink-3">
                  <th className="py-2 pr-3 font-medium">Rank</th><th className="py-2 pr-3 font-medium">Vendor</th>
                  <th className="py-2 pr-3 text-right font-medium">Total</th><th className="py-2 pr-3 font-medium">Terms</th>
                  {weights.map(([k]) => <th key={k} className="py-2 pr-3 text-right font-medium">{CRITERION[k]}</th>)}
                  <th className="py-2 pr-3 text-right font-medium">Score</th><th />
                </tr>
              </thead>
              <tbody>
                {ranked.map((r) => (
                  <tr key={r.id} className={`border-b border-rule last:border-0 ${rfq.awarded_response_id === r.id ? "bg-success-50" : ""}`}>
                    <td className="py-2 pr-3 tabular">{r.rank}</td>
                    <td className="py-2 pr-3 text-ink"><Link to={`/app/vendors/${r.vendor_id}`} className="hover:underline">{r.vendor_name}</Link>
                      {r.source === "quote" && <span className="ml-1 text-ink-3">· from quote</span>}</td>
                    <td className="py-2 pr-3 text-right tabular">{formatCurrency(r.total_inr)}</td>
                    <td className="py-2 pr-3 text-ink-2">{[r.lead_time_days != null && `${r.lead_time_days} d`, r.warranty_months != null && `${r.warranty_months} mo`, r.support_rating && `support ${r.support_rating}/5`].filter(Boolean).join(" · ") || "—"}</td>
                    {weights.map(([k]) => <td key={k} className="py-2 pr-3 text-right tabular text-ink-2">{r.scores[k].toFixed(2)}</td>)}
                    <td className="py-2 pr-3 text-right font-medium tabular">{r.total_score.toFixed(2)}</td>
                    <td className="py-2 text-right">{canRun && <AwardButton rfq={rfq} responseId={r.id} vendorName={r.vendor_name} total={r.total_inr}
                      onAwarded={(reqId) => navigate(`/app/requests/${reqId}`)} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Section title="Invited vendors">
          <ul className="flex flex-col text-13">
            {rfq.invitations.map((i) => (
              <li key={`${i.vendor_id}-${i.round}`} className="flex justify-between gap-3 border-b border-rule py-2 last:border-0">
                <span className="text-ink">{i.vendor_name ?? i.vendor_id.slice(0, 8)}{rfq.round > 1 && <span className="text-ink-3"> · round {i.round}</span>}</span>
                <span className="text-ink-3">{i.responded_at ? `quoted ${formatDateTime(i.responded_at)}` : "no quote yet"}</span>
              </li>
            ))}
          </ul>
        </Section>
        <Section title="Items">
          <ul className="flex flex-col text-13">
            {rfq.items.map((it, n) => (
              <li key={n} className="flex justify-between gap-3 border-b border-rule py-2 last:border-0">
                <span className="text-ink">{it.name}</span><span className="tabular text-ink-2">× {it.quantity}</span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-13 text-ink-3">Vendors quote <span className="font-mono">{rfq.reference}</span> on their quote; e-mailed or dropped quotes are linked within a minute.</p>
        </Section>
      </div>

      {rfq.round > 1 && !rfq.sealed_now && (
        <Section title="Earlier rounds">
          <ul className="flex flex-col text-13">
            {rfq.responses.filter((r) => r.round < rfq.round).map((r) => (
              <li key={`${r.vendor_id}-${r.round}`} className="flex justify-between gap-3 border-b border-rule py-2 last:border-0">
                <span className="text-ink">Round {r.round}: {r.vendor_name}</span>
                <span className="tabular text-ink-2">{r.total_inr != null ? formatCurrency(r.total_inr) : "—"}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
