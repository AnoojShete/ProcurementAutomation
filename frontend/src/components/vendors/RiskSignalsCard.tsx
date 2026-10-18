import { useState } from "react";
import { Save } from "lucide-react";
import { vendorsApi, type ComplianceSignals } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { formatPercent } from "@/lib/format";

/**
 * What the risk model knows about a vendor (BR-7): delivery history and
 * tenure from the platform, and the compliance record finance keeps
 * (certification, breaches, geography, financial stability). Saving
 * re-scores the vendor. Talks only to contract-risk-agent (/vendors).
 */
export function RiskSignalsCard({ vendorId, canEdit, onRescored }: { vendorId: string; canEdit: boolean; onRescored: () => void }) {
  const { data, loading, reload } = useApi(() => vendorsApi.riskSignals(vendorId), [vendorId]);
  const [draft, setDraft] = useState<ComplianceSignals | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  if (loading && !data) return null;
  if (!data) return null;
  const p = data.platform;
  const c = draft ?? data.compliance;
  const set = (patch: Partial<ComplianceSignals>) => setDraft({ ...c, ...patch });

  const save = async () => {
    if (!draft) return;
    setBusy(true);
    setMessage(null);
    try {
      const body: Partial<ComplianceSignals> = {
        security_cert_flag: draft.security_cert_flag,
        geo_risk_flag: draft.geo_risk_flag,
        ...(draft.breach_disclosure_count != null ? { breach_disclosure_count: draft.breach_disclosure_count } : {}),
        ...(draft.financial_stability_score != null ? { financial_stability_score: draft.financial_stability_score } : {}),
      };
      const res = await vendorsApi.updateRiskSignals(vendorId, body);
      setMessage({ ok: true, text: `Saved — re-scored ${res.data.risk.risk_band ?? ""} (${res.data.risk.risk_score?.toFixed(2) ?? "—"}).` });
      setDraft(null);
      reload();
      onRescored();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : "Saving failed." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Risk Signals" />
      <CardBody className="flex flex-col gap-4 text-sm">
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">From platform history</p>
          <dl className="grid grid-cols-2 gap-2">
            <dt className="text-slate-500">Tenure</dt>
            <dd className="text-slate-800">{p.vendor_tenure_months != null ? `${p.vendor_tenure_months} month${p.vendor_tenure_months === 1 ? "" : "s"}` : "—"}</dd>
            <dt className="text-slate-500">On-time delivery</dt>
            <dd className="text-slate-800">
              {p.on_time_delivery_rate != null
                ? `${formatPercent(p.on_time_delivery_rate)} (${p.deliveries_on_time} of ${p.deliveries} within ${p.expected_delivery_days} days)`
                : "No deliveries yet"}
            </dd>
          </dl>
        </div>
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400">Compliance record</p>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex items-center gap-2">
              <input type="checkbox" disabled={!canEdit} checked={!!c.security_cert_flag}
                onChange={(e) => set({ security_cert_flag: e.target.checked })} />
              Security certification (ISO 27001 / SOC 2)
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" disabled={!canEdit} checked={!!c.geo_risk_flag}
                onChange={(e) => set({ geo_risk_flag: e.target.checked })} />
              High-risk geography
            </label>
            <label>
              <span className="mb-1 block text-xs text-slate-500">Breach disclosures</span>
              <input className="field" type="number" min={0} disabled={!canEdit} value={c.breach_disclosure_count ?? ""}
                placeholder="Not recorded"
                onChange={(e) => set({ breach_disclosure_count: e.target.value === "" ? null : Number(e.target.value) })} />
            </label>
            <label>
              <span className="mb-1 block text-xs text-slate-500">Financial stability (0–1)</span>
              <input className="field" type="number" min={0} max={1} step={0.05} disabled={!canEdit}
                value={c.financial_stability_score ?? ""} placeholder="Not recorded"
                onChange={(e) => set({ financial_stability_score: e.target.value === "" ? null : Number(e.target.value) })} />
            </label>
          </div>
        </div>
        {canEdit && (
          <div className="flex items-center justify-end gap-3">
            {message && <span className={message.ok ? "text-success-700" : "text-danger-600"}>{message.text}</span>}
            <Button size="sm" icon={<Save className="size-3.5" />} disabled={!draft} loading={busy} onClick={save}>
              Save and re-score
            </Button>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
