import React from "react";
import { CheckCircle2, XCircle, ArrowRight, Clock, ShieldCheck, ShieldAlert, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { formatCurrency } from "@/lib/format";

export interface NextActionConfig {
  key: string;
  label: string;
  enabled: boolean;
  disabled_reason?: string | null;
  method?: string;
  target?: string;
  onExecute?: () => void;
  secondaryAction?: {
    key: string;
    label: string;
    onExecute?: () => void;
  };
}

interface NextActionBarProps {
  action?: NextActionConfig | null;
  requestId?: string;
  amount?: number;
  currency?: string;
  vendorName?: string;
  vendorClearance?: { cleared: boolean; label?: string };
  slaCountdown?: string;
  isLoading?: boolean;
}

export const NextActionBar: React.FC<NextActionBarProps> = ({
  action,
  requestId,
  amount,
  currency = "INR",
  vendorName,
  vendorClearance,
  slaCountdown,
  isLoading = false,
}) => {
  if (!action) return null;

  return (
    <div className="sticky top-0 z-20 rounded-xl border border-rule-strong/30 bg-sheet/95 backdrop-blur-sm p-4 shadow-sm mb-6 transition-all">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        {/* Left: Summary context */}
        <div className="flex flex-wrap items-center gap-3 text-xs">
          {requestId && (
            <span className="font-mono font-semibold text-ink px-2 py-1 bg-sheet-sunk rounded border border-rule">
              PR-{requestId.slice(0, 8).toUpperCase()}
            </span>
          )}
          {amount != null && (
            <span className="font-semibold text-ink text-sm">
              {formatCurrency(amount, currency)}
            </span>
          )}
          {vendorName && (
            <span className="text-ink-2 font-medium">
              Vendor: <span className="text-ink">{vendorName}</span>
            </span>
          )}
          {vendorClearance && (
            <Badge tone={vendorClearance.cleared ? "success" : "danger"}>
              {vendorClearance.cleared ? (
                <span className="flex items-center gap-1">
                  <ShieldCheck className="size-3" /> Cleared
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <ShieldAlert className="size-3" /> {vendorClearance.label || "Uncleared"}
                </span>
              )}
            </Badge>
          )}
          {slaCountdown && (
            <span className="flex items-center gap-1 text-ink-3">
              <Clock className="size-3.5" /> SLA: {slaCountdown}
            </span>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-3">
          {action.secondaryAction && (
            <Button
              variant="secondary"
              size="sm"
              onClick={action.secondaryAction.onExecute}
              disabled={isLoading}
              className="border-danger/30 text-danger hover:bg-danger-tint"
            >
              {action.secondaryAction.label}
            </Button>
          )}

          <div className="relative group">
            <Button
              variant="primary"
              size="sm"
              onClick={action.onExecute}
              disabled={!action.enabled || isLoading}
              className="gap-1.5 shadow-sm"
            >
              <span>{action.label}</span>
              <ArrowRight className="size-3.5" />
            </Button>

            {!action.enabled && action.disabled_reason && (
              <div className="absolute right-0 top-full mt-1.5 hidden group-hover:flex items-center gap-1.5 px-3 py-1.5 text-xs text-ink bg-sheet border border-rule-strong rounded-lg shadow-popover whitespace-nowrap z-30">
                <AlertCircle className="size-3.5 text-attention" />
                <span>{action.disabled_reason}</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
