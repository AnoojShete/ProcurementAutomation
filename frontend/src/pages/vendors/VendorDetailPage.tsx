import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, Ban, Building2, FileText, IndianRupee, RefreshCcw, ScrollText, ShieldQuestion } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { vendorsApi } from "@/api/vendors";
import { requestsApi } from "@/api/requests";
import { contractsApi } from "@/api/contracts";
import { documentsApi } from "@/api/documents";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { MetricCard } from "@/components/ui/MetricCard";
import { Badge, RiskBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/ErrorState";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Timeline, type TimelineEvent } from "@/components/ui/Timeline";
import { Modal } from "@/components/ui/Modal";
import { RiskGauge } from "@/components/vendors/RiskGauge";
import { formatCurrency, formatDateTime, titleCase } from "@/lib/format";
import { ApiError } from "@/api/client";

export function VendorDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth();
  const { data: vendors, loading, error, reload: reloadVendors } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === id) ?? null;
  usePageHeader(vendor?.name ?? "Vendor", "Vendors");

  const { data: risk, reload: reloadRisk } = useApi(() => vendorsApi.risk(id!), [id]);
  const { data: paymentChanges } = useApi(() => vendorsApi.paymentChanges(id!), [id]);
  const { data: allRequests } = useApi(() => requestsApi.list(200), []);
  const { data: allContracts } = useApi(() => contractsApi.list(200), []);
  const { data: allDocuments } = useApi(() => documentsApi.list(200), []);

  const vendorRequests = useMemo(() => (allRequests ?? []).filter((r) => r.vendor_id === id), [allRequests, id]);
  const vendorContracts = useMemo(() => (allContracts ?? []).filter((c) => c.vendor_id === id), [allContracts, id]);
  const vendorDocuments = useMemo(() => (allDocuments ?? []).filter((d) => d.vendor_id === id), [allDocuments, id]);
  const totalSpend = useMemo(
    () => vendorRequests.filter((r) => r.status === "approved" || r.status === "fulfilled").reduce((s, r) => s + (r.amount ?? 0), 0),
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

  if (loading) return <Skeleton className="h-96" />;
  if (error || !vendor) return <ErrorState message={error ?? "Vendor not found."} onRetry={reloadVendors} />;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Building2 className="size-5 text-slate-400" />
            <h1 className="text-xl font-semibold text-slate-900">{vendor.name}</h1>
            <Badge tone={vendor.status === "active" ? "success" : "neutral"}>{vendor.status}</Badge>
            <RiskBadge band={vendor.risk_band} />
          </div>
          <p className="mt-1 font-mono text-xs text-slate-400">{vendor.id}</p>
        </div>
        {(user?.role === "finance" || user?.role === "admin") && (
          <div className="flex gap-2">
            <Button variant="secondary" icon={<RefreshCcw className="size-4" />} loading={recomputing} onClick={recompute}>
              Recompute Risk
            </Button>
            {user.role === "admin" && (
              <Button variant="destructive" icon={<Ban className="size-4" />} onClick={() => setOffboardOpen(true)}>
                Offboard Vendor
              </Button>
            )}
          </div>
        )}
      </div>
      {recomputeMsg && (recomputeMsg.includes("Unable") ? <InlineError message={recomputeMsg} /> : <InlineSuccess message={recomputeMsg} />)}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard label="Risk Score" value={vendor.risk_score != null ? vendor.risk_score.toFixed(2) : "—"} icon={ShieldQuestion} tone="brand" />
        <MetricCard label="Contracts" value={vendorContracts.length} icon={ScrollText} tone="brand" />
        <MetricCard label="Open Requests" value={openRequests} icon={FileText} tone="warning" />
        <MetricCard label="Approved Spend" value={formatCurrency(totalSpend)} icon={IndianRupee} tone="success" />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Vendor Risk" subtitle="Why is this vendor rated this way?" />
          <CardBody>
            {!risk ? (
              <p className="py-6 text-center text-sm text-slate-500">This vendor hasn't been risk-scored yet.</p>
            ) : (
              <>
                <RiskGauge score={risk.risk_score} band={risk.risk_band} scoredAt={risk.scored_at} />
                <p className="mt-4 mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Contributing Factors</p>
                <div className="flex flex-col gap-2.5">
                  {risk.top_factors.map((f) => {
                    const max = Math.max(...risk.top_factors.map((x) => Math.abs(x.contribution)), 0.001);
                    return (
                      <div key={f.feature} className="flex items-center gap-3">
                        <span className="w-40 shrink-0 truncate text-sm text-slate-600">{titleCase(f.feature)}</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                          <div className="h-full rounded-full bg-intel-500" style={{ width: `${(Math.abs(f.contribution) / max) * 100}%` }} />
                        </div>
                        <span className="w-14 shrink-0 text-right text-xs tabular text-slate-500">{f.contribution.toFixed(3)}</span>
                      </div>
                    );
                  })}
                </div>
                <p className="mt-3 text-xs text-slate-400">Model version {risk.model_version ?? "—"} · vendor-specific factor weights, not a static ranking.</p>
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
        <Card>
          <CardHeader title="Payment Detail Changes" subtitle="Dual control — verifier must differ from submitter" />
          <CardBody>
            {(paymentChanges ?? []).length === 0 ? (
              <p className="text-sm text-slate-500">No payment detail changes on record.</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {paymentChanges!.map((c) => (
                  <li key={c.id} className="flex items-center justify-between text-sm">
                    <span className="text-slate-700">Submitted by {c.submitted_by}</span>
                    <Badge tone={c.status === "verified" ? "success" : c.status === "rejected" ? "danger" : "warning"}>{c.status}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <OffboardModal open={offboardOpen} onClose={() => setOffboardOpen(false)} vendorId={vendor.id} vendorName={vendor.name} onDone={reloadVendors} />
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
