import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check, ShieldAlert, X } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { ledgerApi, paymentControlsApi } from "@/api/controls";
import { documentsApi } from "@/api/documents";
import { vendorsApi } from "@/api/vendors";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { InlineError, InlineInfo, InlineSuccess } from "@/components/ui/ErrorState";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import type { DocumentRecord, LookalikeScenario } from "@/types/api";
import { Explainer } from "./Explainer";
import { DocumentControls } from "./DocumentControls";

export function PaymentPanel({ showcase }: { showcase: boolean }) {
  const { data: pending, reload: reloadPending } = useApi(() => paymentControlsApi.pending(), []);
  const { data: held, reload: reloadHeld } = useApi(() => ledgerApi.matches({ held: true }), []);
  const [channel, setChannel] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [scenario, setScenario] = useState<LookalikeScenario | null>(null);
  const [scenarioDoc, setScenarioDoc] = useState<DocumentRecord | null>(null);

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setMessage(null);
    try {
      await fn();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : "Request failed." });
    } finally {
      setBusy(null);
    }
  };

  // Follow the scenario invoice through the real pipeline.
  useEffect(() => {
    if (!scenario || (scenarioDoc && ["classified", "failed"].includes(scenarioDoc.status))) return;
    const t = setInterval(async () => {
      try {
        const d = (await documentsApi.get(scenario.document_id)).data;
        setScenarioDoc(d);
        if (["classified", "failed"].includes(d.status)) {
          reloadPending();
          reloadHeld();
        }
      } catch {
        /* keep polling */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [scenario, scenarioDoc, reloadPending, reloadHeld]);

  const decide = (vendorId: string, changeId: string, approve: boolean) =>
    run(`${changeId}-${approve}`, async () => {
      const res = await vendorsApi.verifyPaymentChange(vendorId, changeId, channel[changeId] ?? "", approve);
      const released = (res.meta as { payment_holds_released?: number } | undefined)?.payment_holds_released ?? 0;
      setMessage({
        ok: true,
        text: approve
          ? `Bank details verified.${released ? ` ${released} held invoice(s) released for payment.` : ""}`
          : "Change rejected — the vendor's previous bank details stay in force.",
      });
      reloadPending();
      reloadHeld();
    });

  return (
    <div className="flex flex-col gap-4">
      <Explainer
        problem="Existing vendors' bank-detail changes needed verification, but a vendor seen for the first time had whatever bank details its invoice carried written straight onto its record — so an invoice from “De1l Technologies” became a trusted payee."
        control="Bank details from any document go to a verification queue checked by a second person over a channel already on file. Lookalike vendor names are flagged, and their invoices stay on payment hold until verified."
      />
      {message && (message.ok ? <InlineSuccess message={message.text} /> : <InlineError message={message.text} />)}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Bank details awaiting verification" subtitle="Verify by calling the vendor on a number already on file — never one from the document" />
          {!pending || pending.length === 0 ? (
            <CardBody className="text-13 text-slate-500">Nothing waiting.</CardBody>
          ) : (
            <ul className="divide-y divide-surface-border">
              {pending.map((c) => (
                <li key={c.id} className="flex flex-col gap-2 px-4 py-3 text-13">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <Link to={`/app/vendors/${c.vendor_id}`} className="font-medium text-brand-700 hover:underline">
                        {c.vendor_name}
                      </Link>{" "}
                      <span className="text-slate-500">
                        account {c.previous_account_last4 ?? "(none on file)"} → <span className="font-medium text-slate-900">{c.new_account_last4}</span>
                        {c.new_routing_code ? ` · ${c.new_routing_code}` : ""}
                      </span>
                    </span>
                    <span className="flex items-center gap-2 text-xs text-slate-500">
                      {c.source === "document_first_seen" ? <Badge tone="warning">First seen</Badge> : <Badge>Change</Badge>}
                      from {c.submitted_by} · {c.submitted_at ? formatRelativeTime(c.submitted_at) : ""}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      value={channel[c.id] ?? ""}
                      onChange={(e) => setChannel((p) => ({ ...p, [c.id]: e.target.value }))}
                      placeholder="How verified, e.g. called +91 80 4000 1234 (on file)"
                      className="field w-80"
                    />
                    <Button size="sm" icon={<Check className="size-3.5" />} disabled={!channel[c.id]} loading={busy === `${c.id}-true`} onClick={() => decide(c.vendor_id, c.id, true)}>
                      Verify
                    </Button>
                    <Button size="sm" variant="secondary" icon={<X className="size-3.5" />} disabled={!channel[c.id]} loading={busy === `${c.id}-false`} onClick={() => decide(c.vendor_id, c.id, false)}>
                      Reject
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <CardHeader title="Scenario" />
          <CardBody className="flex flex-col gap-2 text-13 text-slate-600">
            <Button
              size="sm"
              variant="secondary"
              icon={<ShieldAlert className="size-3.5" />}
              disabled={!showcase}
              loading={busy === "lookalike"}
              onClick={() =>
                run("lookalike", async () => {
                  setScenarioDoc(null);
                  setScenario((await paymentControlsApi.lookalikeScenario()).data);
                })
              }
            >
              Receive an invoice from a lookalike vendor
            </Button>
            <p>
              Generates an invoice from a near-copy of a real vendor's name with new bank details, and uploads it through
              the normal pipeline.
            </p>
            {scenario && (
              <div className="mt-1 flex flex-col gap-2 rounded-md border border-surface-border bg-surface-subtle p-2.5">
                <p>
                  <span className="font-medium text-slate-900">{scenario.lookalike_name}</span> impersonating{" "}
                  <span className="font-medium text-slate-900">{scenario.impersonated_vendor}</span>, account ••••
                  {scenario.bank_account_last4}.
                </p>
                {!scenarioDoc || !["classified", "failed"].includes(scenarioDoc.status) ? (
                  <InlineInfo message="Processing through the pipeline…" />
                ) : (
                  <>
                    <DocumentControls extracted={scenarioDoc.extracted_fields ?? {}} />
                    <Link to={`/app/documents/${scenario.document_id}`} className="font-medium text-brand-700 hover:underline">
                      Open the document
                    </Link>
                    <p className="text-xs">
                      Its bank details are now in the queue on the left. You uploaded it, so you can't verify it —
                      dual control needs a second person.
                    </p>
                  </>
                )}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Invoices on payment hold" />
        {!held || held.length === 0 ? (
          <CardBody className="text-13 text-slate-500">None.</CardBody>
        ) : (
          <ul className="divide-y divide-surface-border text-13">
            {held.map((h) => (
              <li key={h.document_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                <span>
                  <Link to={`/app/documents/${h.document_id}`} className="font-medium text-brand-700 hover:underline">
                    {h.invoice_number ?? h.document_id.slice(0, 8)}
                  </Link>{" "}
                  <span className="text-slate-500">{h.vendor_name} · {h.hold_reason}</span>
                </span>
                <span className="tabular text-slate-700">{h.amount != null ? formatCurrency(h.amount) : "—"}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
