import { useState } from "react";
import { Link } from "react-router-dom";
import { ShieldCheck, ShieldAlert, AlertCircle, CheckCircle2, Clock, Lock, RefreshCw } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { mandatesApi, type SigningMandate } from "@/api/mandates";
import { businessRulesApi } from "@/api/businessRules";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Modal } from "@/components/ui/Modal";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/format";
import type { BusinessRule } from "@/types/api";

export function SigningAuthorityPage() {
  usePageHeader("Signing Authority");
  const { user } = useAuth();

  const { data: activeData, loading, reload } = useApi(
    () => mandatesApi.getActive().catch(() => ({ data: { active: false, mandate: null } })),
    [],
  );

  const { data: templateData } = useApi(
    () => mandatesApi.getTemplate().catch(() => ({ data: { template_text: "", version: "2026-10-v1" } })),
    [],
  );

  const { data: recentAutoSigned, reload: reloadRecent } = useApi(
    () => mandatesApi.getRecentAutoSigned().catch(() => ({ data: [] })),
    [],
  );

  const { data: rulesData } = useApi<Record<string, BusinessRule[]>>(
    () => businessRulesApi.getAll().catch(() => ({ data: {} })),
    [],
  );

  const maxAutoSignAmount = (() => {
    const rules = rulesData?.contract ?? [];
    const r = rules.find((item) => item.rule_key === "contract.auto_sign_max_amount");
    return typeof r?.current_value === "number" ? r.current_value : 25000;
  })();

  const mandate = activeData?.mandate;
  const isActive = activeData?.active && mandate?.status === "active";

  const daysRemaining = (() => {
    if (!mandate?.valid_until) return 0;
    const diff = new Date(mandate.valid_until).getTime() - Date.now();
    return Math.max(0, Math.ceil(diff / (24 * 3600 * 1000)));
  })();

  // Authorize Modal
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  // Revoke Modal
  const [revokeModalOpen, setRevokeModalOpen] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revokeReason, setRevokeReason] = useState("");
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const handleAuthorize = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) {
      setAuthError("Please enter your current account password to authorize the mandate.");
      return;
    }
    setSubmitting(true);
    setAuthError(null);
    try {
      await mandatesApi.create(password, templateData?.version ?? "2026-10-v1");
      setPassword("");
      setAuthModalOpen(false);
      reload();
      reloadRecent();
    } catch (err: any) {
      setAuthError(err?.message || "Failed to authorize signing mandate. Please check your password.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleRevoke = async () => {
    if (!mandate) return;
    setRevoking(true);
    setRevokeError(null);
    try {
      await mandatesApi.revoke(mandate.id, revokeReason.trim() || undefined);
      setRevokeModalOpen(false);
      setRevokeReason("");
      reload();
      reloadRecent();
    } catch (err: any) {
      setRevokeError(err?.message || "Failed to revoke signing mandate.");
    } finally {
      setRevoking(false);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Overview Card */}
      <Card>
        <CardHeader
          title="Standing Signing Mandate"
          subtitle="Automated digital signing authority for eligible batch approvals"
          action={
            isActive ? (
              <Badge tone="success">
                <CheckCircle2 className="mr-1 size-3.5" />
                Active ({daysRemaining} days remaining)
              </Badge>
            ) : (
              <Badge tone="warning">
                <AlertCircle className="mr-1 size-3.5" />
                {mandate?.status === "expired" ? "Expired" : mandate?.status === "revoked" ? "Revoked" : "No Active Mandate"}
              </Badge>
            )
          }
        />
        <CardBody className="flex flex-col gap-4 text-sm">
          <p className="text-ink-2">
            Under company policy, Finance officers may authorize an explicit 90-day standing mandate allowing the platform to automatically attach their cryptographic signature to approved contracts meeting strict business rules.
          </p>
          <div className="rounded-lg border border-amber-200/80 bg-amber-50/60 p-3 text-xs text-amber-900">
            <span className="font-semibold block text-amber-950 mb-0.5">Legal Disclaimer & Compliance Guidance</span>
            This is an internal authorisation record with a sealed PDF. Whether a counterparty or regulator accepts it as a legally valid electronic signature must be confirmed with legal or finance. Do not claim legal validity anywhere.
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-lg border border-rule bg-sheet-sunk p-3.5">
              <span className="text-xs text-ink-3 block font-medium">Max Spend Per Contract</span>
              <span className="text-lg font-semibold text-ink mt-0.5 block">{formatCurrency(maxAutoSignAmount)}</span>
              <span className="text-[11px] text-ink-3">Enforced dynamically via business rules</span>
            </div>
            <div className="rounded-lg border border-rule bg-sheet-sunk p-3.5">
              <span className="text-xs text-ink-3 block font-medium">Validity Period</span>
              <span className="text-lg font-semibold text-ink mt-0.5 block">90 Days</span>
              <span className="text-[11px] text-ink-3">
                {isActive ? `Expires ${formatDate(mandate?.valid_until)}` : "Renewable on expiry"}
              </span>
            </div>
            <div className="rounded-lg border border-rule bg-sheet-sunk p-3.5">
              <span className="text-xs text-ink-3 block font-medium">Authorized Officer</span>
              <span className="text-lg font-semibold text-ink mt-0.5 block truncate">{user?.display_name || user?.email}</span>
              <span className="text-[11px] text-ink-3">Role: {user?.role}</span>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-rule">
            <div className="text-xs text-ink-3">
              {isActive
                ? `Mandate #${mandate?.id.slice(0, 8)} authorized on ${formatDate(mandate?.created_at)}`
                : "No active mandate currently in effect for your account"}
            </div>
            <div className="flex items-center gap-2">
              {isActive ? (
                <Button variant="destructive" size="sm" onClick={() => setRevokeModalOpen(true)}>
                  Revoke Mandate
                </Button>
              ) : (
                <Button variant="primary" size="sm" onClick={() => setAuthModalOpen(true)}>
                  <ShieldCheck className="mr-1.5 size-4" />
                  Authorize Automated Signing
                </Button>
              )}
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Authorized Legal Text */}
      <Card>
        <CardHeader
          title="Verbatim Mandate Authorization Text"
          subtitle={`Version: ${templateData?.version ?? "2026-10-v1"}`}
        />
        <CardBody>
          <div className="rounded-md border border-rule bg-sheet-sunk p-4 font-mono text-xs leading-relaxed text-ink-2 whitespace-pre-wrap">
            {templateData?.template_text || "Loading template text..."}
          </div>
        </CardBody>
      </Card>

      {/* Recent Auto-Signed Contracts */}
      <Card>
        <CardHeader
          title="Recent Auto-Signed Contracts"
          subtitle="Audit log of contracts executed under your standing mandate"
          action={
            <Button variant="ghost" size="sm" onClick={reloadRecent}>
              <RefreshCw className="mr-1.5 size-3.5" />
              Refresh
            </Button>
          }
        />
        <CardBody>
          {recentAutoSigned && recentAutoSigned.length > 0 ? (
            <div className="divide-y divide-rule border-y border-rule text-sm">
              {recentAutoSigned.map((c: any) => (
                <div key={c.id} className="flex items-center justify-between py-3">
                  <div>
                    <Link
                      to={`/app/contracts/${c.id}`}
                      className="font-medium text-accent hover:underline font-mono text-xs"
                    >
                      CT-{c.id.slice(0, 8)}
                    </Link>
                    <p className="text-xs text-ink-3 mt-0.5">
                      Batch #{c.bulk_batch_id ? c.bulk_batch_id.slice(0, 8) : "—"} · Channel: {c.approval_channel || "portal"} · Signed {formatDateTime(c.signed_at)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge tone="success">Auto-Signed</Badge>
                    <Link to={`/app/contracts/${c.id}`}>
                      <Button variant="secondary" size="sm">
                        View
                      </Button>
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-ink-3">
              No contracts have been automatically signed under your mandate yet.
            </div>
          )}
        </CardBody>
      </Card>

      {/* Authorize Modal */}
      {authModalOpen && (
        <Modal
          open={authModalOpen}
          onClose={() => !submitting && setAuthModalOpen(false)}
          title="Authorize Automated Signing Mandate"
          size="lg"
          footer={
            <div className="flex w-full items-center justify-end gap-2">
              <Button variant="secondary" disabled={submitting} onClick={() => setAuthModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" loading={submitting} disabled={submitting} onClick={handleAuthorize}>
                <Lock className="mr-1.5 size-4" />
                Sign & Authorize Mandate
              </Button>
            </div>
          }
        >
          <form onSubmit={handleAuthorize} className="flex flex-col gap-4 text-sm">
            <p className="text-ink-2 text-xs">
              By authorizing this mandate, you permit the system to automatically apply your digital signature to contracts generated from batch approvals up to <strong>{formatCurrency(maxAutoSignAmount)}</strong>.
            </p>

            <div className="max-h-48 overflow-y-auto rounded border border-rule bg-sheet-sunk p-3 font-mono text-[11px] leading-relaxed text-ink-2 whitespace-pre-wrap">
              {templateData?.template_text}
            </div>

            {authError && <InlineError message={authError} />}

            <div>
              <label className="mb-1 block text-xs font-medium text-ink-2">Confirm Your Account Password *</label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password to sign mandate"
                className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
              />
            </div>
          </form>
        </Modal>
      )}

      {/* Revoke Modal */}
      {revokeModalOpen && (
        <Modal
          open={revokeModalOpen}
          onClose={() => !revoking && setRevokeModalOpen(false)}
          title="Revoke Signing Mandate"
          size="md"
          footer={
            <div className="flex w-full items-center justify-end gap-2">
              <Button variant="secondary" disabled={revoking} onClick={() => setRevokeModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="destructive" loading={revoking} disabled={revoking} onClick={handleRevoke}>
                Confirm Revocation
              </Button>
            </div>
          }
        >
          <div className="flex flex-col gap-3 text-sm">
            <p className="text-ink-2">
              Are you sure you want to revoke this signing mandate? Automated contract signing will stop immediately for all future batch approvals.
            </p>
            {revokeError && <InlineError message={revokeError} />}
            <div>
              <label className="mb-1 block text-xs font-medium text-ink-2">Reason for Revocation (Optional)</label>
              <input
                type="text"
                value={revokeReason}
                onChange={(e) => setRevokeReason(e.target.value)}
                placeholder="e.g. Scheduled rotation, role change"
                className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
              />
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
