import { useState } from "react";
import { Check, X } from "lucide-react";
import { vendorsApi } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import type { VendorPaymentChange } from "@/types/api";

/**
 * Verify or reject one pending bank-detail change (dual control: the
 * server refuses the person who submitted it). The same control on the
 * vendor's page and in Controls → Payment protection. Talks only to
 * document-vendor-agent (/vendors).
 */
export function PaymentChangeVerify({
  change,
  onDone,
}: {
  change: VendorPaymentChange;
  onDone: (result: { ok: boolean; text: string }) => void;
}) {
  const { user } = useAuth();
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState<"verify" | "reject" | null>(null);

  if (!["finance", "admin"].includes(user?.role ?? "")) {
    return <p className="text-xs text-slate-500">Waiting for finance to verify it by calling the vendor.</p>;
  }

  const decide = async (approve: boolean) => {
    setBusy(approve ? "verify" : "reject");
    try {
      const res = await vendorsApi.verifyPaymentChange(change.vendor_id, change.id, channel, approve);
      const released = (res.meta as { payment_holds_released?: number } | undefined)?.payment_holds_released ?? 0;
      onDone({
        ok: true,
        text: approve
          ? `Bank details verified.${released ? ` ${released} held invoice(s) released for payment.` : ""}`
          : "Change rejected — the vendor's previous bank details stay in force.",
      });
    } catch (e) {
      onDone({ ok: false, text: e instanceof ApiError ? e.message : "Request failed." });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        value={channel}
        onChange={(e) => setChannel(e.target.value)}
        placeholder="How verified, e.g. called +91 80 4000 1234 (on file)"
        aria-label="How the change was verified"
        className="field w-80 max-w-full"
      />
      <Button size="sm" icon={<Check className="size-3.5" />} disabled={!channel} loading={busy === "verify"} onClick={() => decide(true)}>
        Verify
      </Button>
      <Button size="sm" variant="secondary" icon={<X className="size-3.5" />} disabled={!channel} loading={busy === "reject"} onClick={() => decide(false)}>
        Reject
      </Button>
    </div>
  );
}
