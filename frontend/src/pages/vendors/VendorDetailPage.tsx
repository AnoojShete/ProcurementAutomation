import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, Ban, FileText, IndianRupee, RefreshCcw, ScrollText } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { vendorsApi } from "@/api/vendors";
import { requestsApi } from "@/api/requests";
import { contractsApi } from "@/api/contracts";
import { documentsApi } from "@/api/documents";
import { Card, CardBody, CardHeader, Section } from "@/components/ui/Card";
import { LedgerStrip, MetricCard } from "@/components/ui/MetricCard";
import { DocketHeader, RefCopy } from "@/components/ui/DocketHeader";
import { Badge, RiskBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Modal } from "@/components/ui/Modal";
import { RiskGauge } from "@/components/vendors/RiskGauge";
import { PaymentChangeVerify } from "@/components/vendors/PaymentChangeVerify";
import { SanctionsScreening } from "@/components/vendors/SanctionsScreening";
import { VendorTaxProfileCard } from "@/components/approvals/TdsActions";
import { formatPercent, formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { ApiError } from "@/api/client";

export function VendorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { data: vendors, loading, error, reload: reloadVendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === id) ?? null;
  usePageHeader(vendor?.name ?? "Vendor", "Vendors");

  const { data: risk, reload: reloadRisk } = useApi(() => vendorsApi.risk(id!), [id]);
  // Phase 3c: how the vendor has actually performed.
  const { data: card, loading: cardLoading } = useApi(() => vendorsApi.scorecard(id!), [id]);
  // Payment-detail changes are finance/admin only on the backend; anyone
  // else would get a 403 and see "no changes" instead of "not for you".
  const canSeePayments = user?.role === "finance" || user?.role === "admin";
  const { data: paymentChanges, reload: reloadPaymentChanges } = useApi(
    () => (canSeePayments ? vendorsApi.paymentChanges(id!) : Promise.resolve({ data: [] })),
    [id, canSeePayments],
  );
  const [paymentMessage, setPaymentMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const { data: allRequests } = useApi(() => requestsApi.list(200), []);
  const { data: allContracts } = useApi(() => contractsApi.list(200), []);
  const { data: allDocuments } = useApi(() => documentsApi.list(200), []);

  const vendorRequests = useMemo(() => (allRequests ?? []).filter((r) => r.vendor_id === id), [allRequests, id]);
  const vendorContracts = useMemo(() => (allContracts ?? []).filter((c) => c.vendor_id === id), [allContracts, id]);
  const vendorDocuments = useMemo(() => (allDocuments ?? []).filter((d) => d.vendor_id === id), [allDocuments, id]);
  const totalSpend = useMemo(
    () => vendorRequests.filter((r) => ["approved", "ordered", "partially_received", "fulfilled"].includes(r.status ?? "")).reduce((s, r) => s + (r.amount ?? 0), 0),
    [vendorRequests],
  );
  const openRequests = vendorRequests.filter((r) => r.status === "pending_approval").length;

  const [recomputing, setRecomputing] = useState(false);
  const [recomputeMsg, setRecomputeMsg] = useState<string | null>(null);
  const recompute = async () => {
    setRecomputing(true);
    setRecomputeMsg(null);
    try {
      await vendorsApi.recomputeRisk(id!);
      setRecomputeMsg("Risk score recomputed.");
      reloadRisk();
      reloadVendors();
    } catch (e) {
      setRecomputeMsg(e instanceof ApiError ? e.message : "Unable to recompute risk.");
    } finally {
      setRecomputing(false);
    }
  };

  const [offboardOpen, setOffboardOpen] = useState(false);
  const [tierModalOpen, setTierModalOpen] = useState(false);
  const [pendingTier, setPendingTier] = useState<string>("");
  const [tierJustification, setTierJustification] = useState<string>("");
  const [tierUpdating, setTierUpdating] = useState(false);
  const [tierError, setTierError] = useState<string | null>(null);

  const timeline: TimelineEvent[] = useMemo(() => {
    const events: TimelineEvent[] = [];
    if (vendor?.created_at) events.push({ key: "onboarded", title: "Vendor onboarded", timestamp: formatDateTime(vendor.created_at) });
    (paymentChanges ?? []).forEach((c) =>
      events.push({
        key: c.id,
        title: c.status === "verified" ? "Payment details verified" : "Payment change submitted (pending verification)",
        timestamp: formatDateTime(c.submitted_at),
        tone: c.status === "verified" ? "success" : "warning",
        description: `Submitted by ${c.submitted_by}`,
      }),
    );
    if (risk?.scored_at) events.push({ key: "risk", title: `Risk recomputed — ${risk.risk_band}`, timestamp: formatDateTime(risk.scored_at), tone: risk.risk_band === "High" ? "danger" : undefined });
    vendorContracts.forEach((c) => {
      if (c.signed_at) events.push({ key: `signed-${c.id}`, title: "Contract signed", timestamp: formatDateTime(c.signed_at), tone: "success" });
      else if (c.generated_at) events.push({ key: `gen-${c.id}`, title: "Contract generated", timestamp: formatDateTime(c.generated_at) });
    });
    return events.sort((a, b) => (b.timestamp ?? "").localeCompare(a.timestamp ?? ""));
  }, [vendor, paymentChanges, risk, vendorContracts]);

  if (loading && !vendors) return <Skeleton className="h-96" />;  // first load only: a reload must not unmount the cards
  if (error || !vendor) return <ErrorState message={error ?? "Vendor not found."} onRetry={reloadVendors} />;

  return (
    <div className="flex flex-col gap-6">
      <DocketHeader
        reference={<RefCopy prefix="VEN" id={vendor.id} />}
        title={vendor.name}
        status={
          <>
            <Badge tone={vendor.status === "active" ? "success" : "neutral"}>{vendor.status}</Badge>
            <RiskBadge band={risk?.final_band ?? vendor.risk_band} ratingStatus={risk?.rating_status} />
          </>
        }
        actions={
          (user?.role === "finance" || user?.role === "admin") && (
            <>
              <Button variant="secondary" icon={<RefreshCcw className="size-4" />} loading={recomputing} onClick={recompute}>
                Recompute Risk
              </Button>
              {user.role === "admin" && (
                <Button variant="destructive" icon={<Ban className="size-4" />} onClick={() => setOffboardOpen(true)}>
                  Offboard Vendor
                </Button>
              )}
            </>
          )
        }
      />
      {recomputeMsg && (recomputeMsg.includes("Unable") ? <InlineError message={recomputeMsg} /> : <InlineSuccess message={recomputeMsg} />)}

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-surface-border bg-sheet px-4 py-3 text-sm shadow-xs">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase text-slate-500">Inherent Tier</span>
            {(user?.role === "finance" || user?.role === "admin") ? (
              <select
                aria-label="Inherent Risk Tier"
                className="rounded-md border border-surface-border bg-sheet px-2.5 py-1 text-xs font-semibold uppercase text-ink"
                value={vendor.inherent_tier || "moderate"}
                onChange={(e) => {
                  const newTier = e.target.value;
                  if (newTier === (vendor.inherent_tier || "moderate")) return;
                  setPendingTier(newTier);
                  setTierJustification("");
                  setTierError(null);
                  setTierModalOpen(true);
                }}
              >
                <option value="low">Low</option>
                <option value="moderate">Moderate</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            ) : (
              <Badge tone="brand">{(vendor.inherent_tier || "moderate").toUpperCase()}</Badge>
            )}
          </div>
          {vendor.website && (
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <span className="font-medium text-slate-400">Website:</span>
              <a
                href={vendor.website.startsWith("http") ? vendor.website : `https://${vendor.website}`}
                target="_blank"
                rel="noreferrer"
                className="font-medium text-brand-600 hover:underline"
              >
                {vendor.website}
              </a>
            </div>
          )}
          {vendor.swift_bic && (
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <span className="font-medium text-slate-400">SWIFT/BIC:</span>
              <span className="font-mono font-medium text-slate-800">{vendor.swift_bic}</span>
            </div>
          )}
          {vendor.bank_name && (
            <div className="flex items-center gap-1.5 text-xs text-slate-600">
              <span className="font-medium text-slate-400">Bank:</span>
              <span className="font-medium text-slate-800">{vendor.bank_name}</span>
            </div>
          )}
        </div>
      </div>

      {/* The risk score lives in the Vendor Risk panel below, not twice. */}
      <LedgerStrip cols={3} label="Vendor figures">
        <MetricCard label="Approved spend" value={formatCurrency(totalSpend)} icon={IndianRupee} to={`/app/requests?scope=all&vendor=${id}&status=approved,ordered,fulfilled`} />
        <MetricCard label="Open requests" value={openRequests} icon={FileText} tone="warning" to={`/app/requests?scope=all&vendor=${id}&status=pending_approval`} />
        <MetricCard label="Contracts" value={vendorContracts.length} icon={ScrollText} to={`/app/contracts?vendor=${id}`} />
      </LedgerStrip>

      <Section title="Scorecard" subtitle="From this platform's own records; recomputed when you open the page and nightly. RFQ scoring uses the on-time rate.">
        <LedgerStrip cols={4} loading={cardLoading && !card} label="Vendor scorecard">
          <MetricCard label="On-time deliveries" value={card?.on_time_rate != null ? formatPercent(card.on_time_rate) : "—"}
            hint={card ? (card.deliveries ? `${card.deliveries_on_time} of ${card.deliveries} within ${card.expected_delivery_days} days` : "no deliveries yet") : undefined}
            tone={card?.on_time_rate != null && card.on_time_rate < 0.8 ? "warning" : "neutral"} />
          <MetricCard label="Invoice accuracy" value={card?.invoice_accuracy != null ? formatPercent(card.invoice_accuracy) : "—"}
            hint={card ? (card.invoices ? `${card.invoices} invoices matched or checked` : "no invoices yet") : undefined}
            tone={card?.invoice_accuracy != null && card.invoice_accuracy < 0.9 ? "warning" : "neutral"} />
          <MetricCard label="RFQ response rate" value={card?.rfq_response_rate != null ? formatPercent(card.rfq_response_rate) : "—"}
            hint={card ? (card.rfq_invitations ? `${card.rfq_invitations} invitations` : "not invited yet") : undefined} />
          <MetricCard label="SLA breaches" value={card?.sla_breaches ?? "—"} tone={card?.sla_breaches ? "danger" : "neutral"}
            hint="months with a service credit" />
        </LedgerStrip>
      </Section>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Vendor Risk"
            action={
              <Link
                to={`/app/vendors/${id}/risk`}
                className="inline-flex items-center gap-1 text-xs font-semibold text-brand-600 hover:text-brand-800"
              >
                Full risk scorecard
              </Link>
            }
          />
          <CardBody>
            {!risk ? (
              <p className="py-6 text-center text-sm text-slate-500">This vendor hasn't been risk-scored yet.</p>
            ) : (
              <>
                <RiskGauge score={risk.risk_score} band={risk.risk_band} scoredAt={risk.scored_at} pointsSoFar={risk.total_points} ratingStatus={risk.rating_status} />
                {risk.signals_total != null && (
                  <p className="mt-2 text-xs text-slate-500">
                    Based on <span className="font-medium text-slate-700">{risk.signals_used} of {risk.signals_total}</span> signals on file
                    {risk.signals_used! < risk.signals_total ? " — missing ones are left out, not guessed." : "."}
                  </p>
                )}
                {risk.headline && (
                  <div className={`mt-3 rounded-lg border p-3 text-xs leading-relaxed ${
                    risk.rating_status === "provisional" || risk.risk_band === "High"
                      ? "border-amber-400 bg-amber-50 text-amber-950"
                      : "border-slate-200 bg-slate-50 text-slate-800"
                  }`}>
                    <div className="flex items-start gap-2">
                      <AlertTriangle className={`size-4 shrink-0 mt-0.5 ${
                        risk.rating_status === "provisional" || risk.risk_band === "High" ? "text-amber-600" : "text-slate-500"
                      }`} />
                      <div>
                        <span className="font-semibold">Rating Rationale:</span> {risk.headline}
                      </div>
                    </div>
                  </div>
                )}
                {((risk.provisional?.reasons ?? risk.provisional_reasons ?? []).length > 0) && (
                  <div className="mt-2.5 rounded-md border border-amber-300 bg-amber-50/60 p-2.5 text-xs text-amber-950">
                    <span className="font-semibold">Provisional Rating Flags:</span>
                    <ul className="mt-1 list-disc list-inside space-y-0.5 text-11">
                      {(risk.provisional?.reasons ?? risk.provisional_reasons ?? []).map((r: any, i: number) => (
                        <li key={i}>{typeof r === "string" ? r : r.message || r.code}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(risk.top_factors ?? []).filter((f) => f.override).map((f) => (
                  <div key={f.feature} className="mt-3 rounded-md border border-danger-500/30 bg-danger-50 px-3 py-2 text-13 text-slate-800">
                    <span className="font-medium">Hard override:</span> {f.reason} — rated High regardless of the model score.
                  </div>
                ))}
                {(risk.overrides?.length ?? 0) > 0 && (
                  <p className="mt-2 text-xs text-slate-500">
                    Hard checks:{" "}
                    {risk.overrides!.map((c) => `${(c.rule_id ?? c.check ?? "check").toUpperCase()} ${c.status.replace("_", " ")}`).join(" · ")}
                  </p>
                )}
                <p className="mb-2 mt-5 text-13 font-medium text-ink-2">Contributing factors</p>
                {(risk.top_factors ?? []).filter((f) => !f.override).length === 0 && (
                  <p className="text-sm text-slate-500">
                    {risk.rating_status === "provisional"
                      ? "No penalty points observed (0 risk points). Rated High Risk (provisional) because vendor identity (GSTIN / Incorporation) is not yet verified on file."
                      : "No risk points on file. All assessed signals are clear."}
                  </p>
                )}
                <div className="flex flex-col gap-2.5">
                  {(risk.top_factors ?? []).filter((f) => !f.override).map((f, _i, factors) => {
                    const max = Math.max(...factors.map((x) => Math.abs(x.contribution)), 0.001);
                    return (
                      <div key={f.feature} className="flex items-center gap-3">
                        <span className="w-40 shrink-0 truncate text-sm text-slate-600">{titleCase(f.feature)}</span>
                        <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-sheet-sunk">
                          <div className="h-full bg-ink-2" style={{ width: `${(Math.abs(f.contribution) / max) * 100}%` }} />
                        </div>
                        <span className="w-14 shrink-0 text-right text-xs tabular text-slate-500">{f.contribution.toFixed(3)}</span>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-xs text-slate-400">
                  Model version {risk.model_version ? risk.model_version.replace("_", " ").toUpperCase() : "RULESET V2"} · vendor-specific factor weights, not a static ranking.
                </p>
              </>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Vendor Timeline" />
          <CardBody>
            <Timeline events={timeline} />
          </CardBody>
        </Card>
      </div>

      <SanctionsScreening
        vendorId={vendor.id}
        canAct={user?.role === "finance" || user?.role === "admin"}
        onRescored={() => { reloadRisk(); reloadVendors(); }}
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Documents" subtitle={`${vendorDocuments.length} matched to this vendor`} />
          <CardBody>
            {vendorDocuments.length === 0 ? (
              <p className="text-sm text-slate-500">No documents matched to this vendor yet.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {vendorDocuments.slice(0, 6).map((d) => (
                  <li key={d.id} className="flex items-center justify-between text-sm">
                    <span className="truncate text-slate-700">{d.original_filename}</span>
                    <Badge tone={d.needs_review ? "warning" : "success"}>{d.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        {user?.role !== "requester" && <VendorTaxProfileCard vendorId={vendor.id} />}
        {canSeePayments && (
          <Card>
            <CardHeader title="Payment Detail Changes" subtitle="Dual control — verifier must differ from submitter" />
            <CardBody>
              {(paymentChanges ?? []).length === 0 ? (
                <p className="text-sm text-slate-500">No payment detail changes on record.</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {paymentMessage && (paymentMessage.ok ? <InlineSuccess message={paymentMessage.text} /> : <InlineError message={paymentMessage.text} />)}
                  {paymentChanges!.map((c) => (
                    <li key={c.id} className="flex flex-col gap-2 text-sm">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-700">
                          {c.new_account_last4 ? `Account …${c.new_account_last4}` : "Change"} · submitted by {c.submitted_by}
                        </span>
                        <Badge tone={c.status === "verified" ? "success" : c.status === "rejected" ? "danger" : "warning"}>{c.status}</Badge>
                      </div>
                      {c.status === "pending" && (
                        <PaymentChangeVerify
                          change={c}
                          onDone={(result) => {
                            setPaymentMessage(result);
                            if (result.ok) reloadPaymentChanges();
                          }}
                        />
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
        )}
      </div>

      <OffboardModal open={offboardOpen} onClose={() => setOffboardOpen(false)} vendorId={vendor.id} vendorName={vendor.name} onDone={reloadVendors} />

      <Modal
        open={tierModalOpen}
        onClose={() => {
          if (!tierUpdating) setTierModalOpen(false);
        }}
        title="Change Inherent Risk Tier"
      >
        <div className="flex flex-col gap-4 text-sm">
          <p className="text-slate-600">
            Updating inherent tier for <strong>{vendor.name}</strong> from{" "}
            <span className="font-semibold uppercase text-slate-700">{vendor.inherent_tier || "moderate"}</span> to{" "}
            <span className="font-semibold uppercase text-brand-600">{pendingTier}</span>.
          </p>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-slate-700">
              Justification / Business Rationale <span className="text-slate-400 font-normal">(saved to audit log)</span>:
            </label>
            <input
              type="text"
              className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm text-ink focus:border-brand-500 focus:outline-none"
              placeholder="e.g. Higher operational criticality or updated inherent profile"
              value={tierJustification}
              onChange={(e) => setTierJustification(e.target.value)}
              disabled={tierUpdating}
            />
          </div>
          {tierError && <InlineError message={tierError} />}
          <div className="flex justify-end gap-2 pt-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setTierModalOpen(false)}
              disabled={tierUpdating}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={tierUpdating}
              onClick={async () => {
                setTierUpdating(true);
                setTierError(null);
                try {
                  await vendorsApi.update(vendor.id, {
                    inherent_tier: pendingTier,
                    justification: tierJustification.trim() || `Inherent tier updated to ${pendingTier} by ${user?.email || "admin"}`,
                  });
                  setTierModalOpen(false);
                  reloadVendors();
                  await recompute();
                } catch (err) {
                  setTierError(err instanceof ApiError ? err.message : "Failed to update inherent tier.");
                } finally {
                  setTierUpdating(false);
                }
              }}
            >
              Confirm Change
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function OffboardModal({
  open,
  onClose,
  vendorId,
  vendorName,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  vendorId: string;
  vendorName: string;
  onDone: () => void;
}) {
  const { user } = useAuth();
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<number | null>(null);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await vendorsApi.offboard(vendorId, user!.email, reason || "Offboarded via admin console");
      setDone(res.data.contracts_flagged.length);
      onDone();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to offboard vendor.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title={`Offboard ${vendorName}`}>
      <div className="flex flex-col gap-3">
        <div className="flex items-start gap-2 rounded-lg border border-warning-50 bg-warning-50 px-3 py-2 text-sm text-warning-700">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" />
          <span>
            This revokes portal access and flags every active contract for reconciliation. It never auto-closes
            contracts — a human confirms final invoice/payment status.
          </span>
        </div>
        <textarea
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder="Reason for offboarding…"
          className="w-full resize-none rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
        />
        {error && <InlineError message={error} />}
        {done != null && <InlineSuccess message={`Offboarded. ${done} contract(s) flagged for reconciliation.`} />}
        {done == null && (
          <Button variant="destructive" loading={submitting} onClick={submit}>
            Confirm Offboard
          </Button>
        )}
      </div>
    </Modal>
  );
}
