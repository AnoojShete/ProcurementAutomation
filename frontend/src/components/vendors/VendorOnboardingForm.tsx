import { useState } from "react";
import { AlertTriangle, ShieldCheck, UserPlus } from "lucide-react";
import { vendorsApi, type ProfileCheck, type VendorProfileInput } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";

const FIELDS: { key: keyof VendorProfileInput; label: string; placeholder?: string; wide?: boolean }[] = [
  { key: "name", label: "Legal name *", placeholder: "Acme Cloud Pvt Ltd", wide: true },
  { key: "country", label: "Country (ISO alpha-2) *", placeholder: "e.g. IN, US, GB, DE" },
  { key: "contact_email", label: "Contact email", placeholder: "accounts@vendor.com" },
  { key: "contact_phone", label: "Contact phone", placeholder: "+91 98765 43210" },
  { key: "address", label: "Address", wide: true },
  { key: "category", label: "Category", placeholder: "Software, hardware, services…" },
  { key: "gstin", label: "GSTIN", placeholder: "27AAPFU0939F1ZV" },
  { key: "bank_account_number", label: "Bank account number" },
  { key: "routing_code", label: "IFSC", placeholder: "HDFC0001234" },
  { key: "payment_beneficiary_name", label: "Beneficiary name", wide: true },
];

/**
 * Onboard a vendor (BR-4). The profile is checked by the server first:
 * errors block, look-alike names and a missing GSTIN need an explicit
 * confirmation. Bank details go to two-person verification, not live.
 * Talks only to document-vendor-agent (/vendors).
 */
export function VendorOnboardingForm({
  open,
  onClose,
  onOnboarded,
}: {
  open: boolean;
  onClose: () => void;
  onOnboarded: (vendorId: string) => void;
}) {
  const [profile, setProfile] = useState<VendorProfileInput>({ name: "" });
  const [check, setCheck] = useState<ProfileCheck | null>(null);
  const [confirmed, setConfirmed] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof VendorProfileInput, value: string) => {
    setProfile((p) => ({ ...p, [key]: value }));
    setCheck(null); // any edit needs a fresh check
  };

  const runCheck = async () => {
    setBusy("check");
    setError(null);
    try {
      const res = await vendorsApi.validateOnboarding(profile);
      setCheck(res.data);
      setConfirmed((c) => c.filter((code) => res.data.needs_confirmation.includes(code)));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Check failed.");
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    setBusy("save");
    setError(null);
    try {
      const res = await vendorsApi.onboard({ ...profile, confirm: confirmed, no_gstin_reason: reason || undefined });
      onOnboarded(res.data.id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Onboarding failed.");
    } finally {
      setBusy(null);
    }
  };

  const errorFor = (key: string) => check?.errors.filter((e) => e.field === key) ?? [];
  const needsReason = check?.needs_confirmation.includes("no_gstin") ?? false;
  const allConfirmed =
    check?.needs_confirmation.every((c) => confirmed.includes(c)) && (!needsReason || reason.trim().length > 0);
  const canSave = !!check?.ok && !!allConfirmed;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Onboard vendor"
      size="lg"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" icon={<ShieldCheck className="size-3.5" />} loading={busy === "check"}
            disabled={!profile.name.trim()} onClick={runCheck}>
            Check profile
          </Button>
          <Button icon={<UserPlus className="size-3.5" />} loading={busy === "save"} disabled={!canSave} onClick={save}>
            Onboard
          </Button>
        </div>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        {FIELDS.map((f) => (
          <label key={f.key} className={f.wide ? "col-span-2" : ""}>
            <span className="mb-1 block text-xs font-medium text-slate-600">{f.label}</span>
            <input
              className="field"
              value={(profile[f.key] as string | undefined) ?? ""}
              placeholder={f.placeholder}
              onChange={(e) => set(f.key, e.target.value)}
            />
            {errorFor(f.key).map((e) => (
              <span key={e.message} className="mt-1 block text-xs text-danger-600">{e.message}</span>
            ))}
          </label>
        ))}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Bank details are not used until a second person verifies them by phone (Controls → Payment protection).
      </p>

      {check?.ok && check.warnings.length > 0 && (
        <div className="mt-4 flex flex-col gap-2 rounded-lg border border-warning-500/40 bg-warning-50 p-3">
          {check.warnings.map((w) => (
            <label key={w.code} className="flex items-start gap-2 text-sm text-slate-700">
              {check.needs_confirmation.includes(w.code ?? "") ? (
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={confirmed.includes(w.code!)}
                  onChange={(e) =>
                    setConfirmed((c) => (e.target.checked ? [...c, w.code!] : c.filter((x) => x !== w.code)))
                  }
                />
              ) : (
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning-600" />
              )}
              <span>{w.message}</span>
            </label>
          ))}
          {needsReason && (
            <input
              className="field"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why no GSTIN, e.g. foreign vendor (US), unregistered under ₹20 lakh"
              aria-label="Reason for no GSTIN"
            />
          )}
        </div>
      )}
      {check?.ok && check.warnings.length === 0 && (
        <p className="mt-4 text-sm text-success-700">Profile checks passed.</p>
      )}
      {error && <p className="mt-3 text-sm text-danger-600">{error}</p>}
    </Modal>
  );
}
