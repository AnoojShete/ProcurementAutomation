import { useState } from "react";
import { ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { vendorsApi } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/format";

/**
 * Sanctions screening for one vendor (FR-14): the latest result against the
 * consolidated sanctions list, a "screen now" button, and — for a potential
 * match — clearing it with a written reason (finance/admin, audit-logged).
 * A match is a hard override in the risk model until cleared. Talks only
 * to contract-risk-agent (/vendors).
 */
export function SanctionsScreening({ vendorId, canAct, onRescored }: { vendorId: string; canAct: boolean; onRescored: () => void }) {
  const { data, loading, reload } = useApi(() => vendorsApi.sanctions(vendorId), [vendorId]);
  const [busy, setBusy] = useState<"screen" | "clear" | null>(null);
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  if (loading && !data) return null;
  if (!data) return null;
  const latest = data.latest;

  const act = async (kind: "screen" | "clear") => {
    setBusy(kind);
    setMessage(null);
    try {
      const res = kind === "screen" ? await vendorsApi.screenSanctions(vendorId) : await vendorsApi.clearSanctionsFlag(vendorId, reason);
      const st = res.data.screening.status;
      setMessage({ ok: true, text: st === "potential_match" ? "Potential match found — vendor rated High until reviewed." : st === "cleared" ? "Match cleared and recorded." : "No match on the sanctions list." });
      setReason("");
      reload();
      onRescored();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : "Request failed." });
    } finally {
      setBusy(null);
    }
  };

  const status = !latest ? (
    <Badge tone="neutral">Not screened</Badge>
  ) : latest.status === "potential_match" ? (
    <Badge tone="danger">Potential match</Badge>
  ) : latest.status === "cleared" ? (
    <Badge tone="warning">Match cleared</Badge>
  ) : (
    <Badge tone="success">Clear</Badge>
  );
  const Icon = !latest ? ShieldQuestion : latest.status === "potential_match" ? ShieldAlert : ShieldCheck;

  return (
    <Card>
      <CardHeader
        title="Sanctions Screening"
        subtitle={data.list.available ? `Consolidated sanctions list · ${data.list.entries?.toLocaleString()} companies · ${data.list.version}` : "No sanctions list downloaded yet (./scripts/download-sanctions.sh)"}
      />
      <CardBody className="flex flex-col gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className="size-4 text-slate-500" />
          {status}
          {latest && (
            <span className="text-xs text-slate-500">
              “{latest.screened_name}” · {formatDateTime(latest.screened_at)} · threshold {latest.threshold ?? "—"}
            </span>
          )}
          {canAct && data.list.available && (
            <Button size="sm" variant="secondary" className="ml-auto" loading={busy === "screen"} onClick={() => act("screen")}>
              Screen now
            </Button>
          )}
        </div>
        {latest && latest.matches.length > 0 && (
          <table className="w-full text-left text-xs">
            <thead className="text-slate-500">
              <tr><th className="py-1">Listed company</th><th>Matched name</th><th>Score</th><th>Countries</th><th>Lists</th></tr>
            </thead>
            <tbody>
              {latest.matches.map((m) => (
                <tr key={m.entity_id} className="border-t border-surface-border">
                  <td className="py-1 font-medium text-slate-800">{m.listed_name}</td>
                  <td>{m.matched_name}</td>
                  <td className="tabular-nums">{m.score}</td>
                  <td className="uppercase">{m.countries || "—"}</td>
                  <td>{m.lists}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {latest?.status === "cleared" && latest.justification && (
          <p className="text-xs text-slate-600">Cleared by {latest.screened_by}: {latest.justification}</p>
        )}
        {canAct && latest?.status === "potential_match" && (
          <div className="flex flex-col gap-2 rounded-md border border-danger-500/30 bg-danger-50 p-3">
            <span className="text-xs text-slate-700">If this is a different company, record why (at least 20 characters) — it is kept in the audit log.</span>
            <textarea className="field h-16 py-1.5" value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Different company: CIN U72200KA2010PTC123456 and registered address checked" aria-label="Reason for clearing" />
            <Button size="sm" className="self-end" disabled={reason.trim().length < 20} loading={busy === "clear"} onClick={() => act("clear")}>
              Clear match
            </Button>
          </div>
        )}
        {message && <span className={message.ok ? "text-success-700" : "text-danger-600"}>{message.text}</span>}
      </CardBody>
    </Card>
  );
}
