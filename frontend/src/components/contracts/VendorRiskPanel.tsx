import { ShieldAlert, ShieldCheck } from "lucide-react";
import { RiskBadge } from "@/components/ui/Badge";
import { formatDate, titleCase } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { SigningRisk } from "@/types/api";

/**
 * The vendor's risk as the signer should see it before signing (BR-6):
 * band, score, the model's main reasons and any hard override. Shown on
 * the contract page and in the signing dialog.
 */
export function VendorRiskPanel({ risk, compact = false }: { risk: SigningRisk; compact?: boolean }) {
  const alarming = risk.acknowledgement_required;
  const Icon = alarming ? ShieldAlert : ShieldCheck;
  return (
    <div
      className={cn(
        "rounded-lg border p-3.5 text-sm",
        alarming ? "border-danger-500/30 bg-danger-50" : "border-surface-border bg-sheet",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={cn("size-4", alarming ? "text-danger-600" : "text-success-600")} />
        <span className="font-medium text-slate-800">Vendor risk</span>
        <RiskBadge band={risk.risk_band} ratingStatus={risk.rating_status} showProvisional />
        {risk.risk_score != null && <span className="text-xs text-slate-500">score {risk.risk_score.toFixed(2)}</span>}
        {risk.scored_at && <span className="text-xs text-slate-400">· scored {formatDate(risk.scored_at)}</span>}
      </div>
      {risk.overrides.map((o) => (
        <p key={o.check} className="mt-2 text-13 font-medium text-danger-700">
          Hard override — {o.reason ?? titleCase(o.check)}
        </p>
      ))}
      {!compact && risk.reasons.length > 0 && (
        <p className="mt-2 text-xs text-slate-600">
          Main factors: {risk.reasons.map((r) => titleCase(r.feature)).join(", ")}
        </p>
      )}
      {risk.signing_blocked ? (
        <p className="mt-2 text-13 font-medium text-danger-700">{risk.blocked_reason}</p>
      ) : alarming && (
        <p className="mt-2 text-xs text-slate-700">
          {risk.overrides.length ? "" : `${risk.acknowledgement_reason ?? ""} `}Signing needs an explicit acknowledgement.
        </p>
      )}
    </div>
  );
}
