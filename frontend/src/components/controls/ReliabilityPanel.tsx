import { useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, RotateCcw, Trash2, Wrench, Zap } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { opsApi } from "@/api/controls";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge, StatusDot } from "@/components/ui/Badge";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatRelativeTime } from "@/lib/format";
import type { DlqEntry, ReconcileResult } from "@/types/api";
import { Explainer } from "./Explainer";

export function ReliabilityPanel({ showcase }: { showcase: boolean }) {
  const { data: status, reload: reloadStatus } = useApi(() => opsApi.eventing(), []);
  const [dlqFilter, setDlqFilter] = useState<"open" | "replayed" | "discarded">("open");
  const { data: dlq, reload: reloadDlq } = useApi(() => opsApi.dlq(dlqFilter), [dlqFilter]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [repaired, setRepaired] = useState<ReconcileResult[] | null>(null);

  const refresh = () => {
    reloadStatus();
    reloadDlq();
  };

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

  const inject = () =>
    run("inject", async () => {
      const res = await opsApi.injectOutOfOrderEvent();
      setMessage({
        ok: true,
        text: `Published invoice.matched for PR-${res.data.purchase_request_id.slice(0, 8)}, which is still awaiting approval. Watch it land in the dead-letter queue below.`,
      });
      setTimeout(refresh, 2500);
    });

  const reconcile = () =>
    run("reconcile", async () => {
      const res = await opsApi.reconcile();
      setRepaired(res.data);
      setMessage({
        ok: true,
        text: res.data.length
          ? `Repaired ${res.data.length} request(s) whose contract.signed event had been lost.`
          : "Nothing to repair — every signed contract's request is already fulfilled.",
      });
    });

  const replay = (entry: DlqEntry) =>
    run(`replay-${entry.id}`, async () => {
      const res = await opsApi.replay(entry);
      setMessage(
        res.data.status === "replayed"
          ? { ok: true, text: "Replayed successfully." }
          : { ok: false, text: `Replay failed again: ${res.data.error}` },
      );
      refresh();
    });

  const discard = (entry: DlqEntry) =>
    run(`discard-${entry.id}`, async () => {
      await opsApi.discard(entry.id);
      refresh();
    });

  const services = Object.entries(status?.outbox ?? {});

  return (
    <div className="flex flex-col gap-4">
      <Explainer
        problem="Services used to commit a change and publish its event as two separate steps; a crash in between lost the event, and consumers dropped any event their handler failed on. That's how requests got stuck at approved with a signed contract."
        control="Events are written to an outbox in the same transaction as the change and relayed to Kafka. Consumers retry, then park failures in a dead-letter queue with the error. A state machine refuses impossible transitions, and a reconciler repairs anything lost before this existed."
      />
      {message && (message.ok ? <InlineSuccess message={message.text} /> : <InlineError message={message.text} />)}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Outbox"
            subtitle="Events committed with their state change, per service"
            action={
              <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} onClick={refresh}>
                Refresh
              </Button>
            }
          />
          <table className="w-full text-13">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-slate-500">
                <th className="px-4 py-2 font-semibold">Service</th>
                <th className="px-4 py-2 text-right font-semibold">Waiting to send</th>
                <th className="px-4 py-2 text-right font-semibold">Sent (last hour)</th>
                <th className="px-4 py-2 font-semibold">Oldest waiting</th>
              </tr>
            </thead>
            <tbody>
              {services.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-4 text-slate-500">No events through the outbox yet.</td>
                </tr>
              )}
              {services.map(([svc, s]) => (
                <tr key={svc} className="border-b border-surface-border last:border-0">
                  <td className="px-4 py-2 font-medium text-slate-900">{svc}</td>
                  <td className="px-4 py-2 text-right tabular">
                    {s.pending > 0 ? <span className="font-medium text-warning-700">{s.pending}</span> : 0}
                  </td>
                  <td className="px-4 py-2 text-right tabular">{s.sent_last_hour}</td>
                  <td className="px-4 py-2 text-slate-600">
                    {s.oldest_pending ? formatRelativeTime(s.oldest_pending) : "—"}
                    {s.last_error && <span className="ml-2 text-xs text-danger-600">{s.last_error}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardHeader title="Scenarios" />
          <CardBody className="flex flex-col gap-3 text-13 text-slate-600">
            <div>
              <Button
                size="sm"
                variant="secondary"
                icon={<Zap className="size-3.5" />}
                loading={busy === "inject"}
                disabled={!showcase}
                onClick={inject}
              >
                Send an out-of-order event
              </Button>
              <p className="mt-1.5">
                Publishes “invoice matched” for a request nobody has approved. The state machine refuses it and the
                event is parked with the reason, instead of corrupting the request or vanishing.
              </p>
            </div>
            <div className="border-t border-surface-border pt-3">
              <Button size="sm" variant="secondary" icon={<Wrench className="size-3.5" />} loading={busy === "reconcile"} onClick={reconcile}>
                Run reconciler now
              </Button>
              <p className="mt-1.5">Finds requests whose contract is signed but that never moved on, and applies the missed step. Also runs hourly.</p>
            </div>
          </CardBody>
        </Card>
      </div>

      {repaired && repaired.length > 0 && (
        <Card>
          <CardHeader title="Reconciler repairs" subtitle="Each one is written to the audit log" />
          <ul className="divide-y divide-surface-border text-13">
            {repaired.map((r) => (
              <li key={r.request_id} className="flex items-center justify-between px-4 py-2">
                <Link to={`/app/requests/${r.request_id}`} className="font-medium text-brand-700 hover:underline">
                  PR-{r.request_id.slice(0, 8)}
                </Link>
                <span className="text-slate-600">
                  contract {r.contract_id.slice(0, 8)} → <span className="font-medium text-slate-900">{r.outcome}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Dead-letter queue"
          subtitle="Events a consumer couldn't process after retries — kept with the error until someone replays or discards them"
          action={
            <select
              value={dlqFilter}
              onChange={(e) => setDlqFilter(e.target.value as typeof dlqFilter)}
              className="h-7 rounded-md border border-surface-border bg-white px-2 text-xs"
            >
              <option value="open">Open</option>
              <option value="replayed">Replayed</option>
              <option value="discarded">Discarded</option>
            </select>
          }
        />
        {!dlq || dlq.length === 0 ? (
          <CardBody className="text-13 text-slate-500">Nothing here.</CardBody>
        ) : (
          <ul className="divide-y divide-surface-border">
            {dlq.map((e) => (
              <li key={e.id} className="flex flex-col gap-2 px-4 py-3 text-13 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-slate-900">{e.topic}</span>
                    <Badge>{e.consumer}</Badge>
                    <span className="text-xs text-slate-500">
                      {e.attempts} attempt{e.attempts === 1 ? "" : "s"} · {formatRelativeTime(e.failed_at)}
                      {e.event.source_service ? ` · from ${e.event.source_service}` : ""}
                    </span>
                  </div>
                  <p className="mt-1 break-words font-mono text-xs text-danger-600">{e.error}</p>
                  {e.status !== "open" && (
                    <p className="mt-1 text-xs text-slate-500">
                      <StatusDot tone={e.status === "replayed" ? "success" : "neutral"}>{e.status}</StatusDot> by {e.resolved_by}
                    </p>
                  )}
                </div>
                {e.status === "open" && (
                  <div className="flex shrink-0 gap-2">
                    <Button size="sm" variant="secondary" icon={<RotateCcw className="size-3.5" />} loading={busy === `replay-${e.id}`} onClick={() => replay(e)}>
                      Replay
                    </Button>
                    <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} loading={busy === `discard-${e.id}`} onClick={() => discard(e)}>
                      Discard
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
