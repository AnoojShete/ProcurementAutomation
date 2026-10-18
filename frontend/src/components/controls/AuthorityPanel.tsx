import { useState } from "react";
import { Link } from "react-router-dom";
import { Plus, UserX } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { authorityApi } from "@/api/controls";
import { requestsApi } from "@/api/requests";
import { ApiError } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusDot } from "@/components/ui/Badge";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { formatCurrency, formatDate } from "@/lib/format";
import { Explainer } from "./Explainer";

const LEVELS = [
  { key: "dept_manager", label: "Department manager" },
  { key: "finance_head", label: "Finance head" },
];

export function AuthorityPanel() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const { data, reload } = useApi(() => authorityApi.get(), []);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [scenario, setScenario] = useState<{ requestId: string; outcome: string } | null>(null);

  const [level, setLevel] = useState("dept_manager");
  const [email, setEmail] = useState("");
  const [limit, setLimit] = useState("");
  const [delegate, setDelegate] = useState("");
  const [delegLevel, setDelegLevel] = useState("dept_manager");
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setMessage(null);
    try {
      await fn();
      reload();
    } catch (e) {
      setMessage({ ok: false, text: e instanceof ApiError ? e.message : "Request failed." });
    } finally {
      setBusy(null);
    }
  };

  // Raise a request as the signed-in user, then try to approve it.
  const selfApproval = () =>
    run("self", async () => {
      const created = await requestsApi.create({
        request_type: "saas",
        requested_by: user!.email,
        department: "IT",
        amount: 3000,
        currency: "INR",
        items: [{ name: "Showcase: self-approval attempt", quantity: 1, unit_price: 3000 }],
        comments: "Showcase — separation of duties",
      });
      const id = created.data.id;
      let outcome = "";
      try {
        await requestsApi.approve(id, user!.email, "self-approval attempt");
        outcome = "Approved — separation of duties is NOT enforced.";
      } catch (e) {
        outcome = e instanceof ApiError ? `Blocked (${e.status}): ${e.message}` : "Blocked.";
      }
      // Clean up: the requester may still reject their own request.
      await requestsApi.reject(id, user!.email, "showcase cleanup").catch(() => undefined);
      setScenario({ requestId: id, outcome });
    });

  const assignments = (data?.assignments ?? []).filter((a) => a.active);

  return (
    <div className="flex flex-col gap-4">
      <Explainer
        problem="Any approver, finance or admin user could approve any request at any level — including one they raised themselves."
        control="Each approval level has assigned approvers with an amount limit. Nobody approves their own request or two levels of the same request; stand-ins get time-boxed, audited delegations."
      />
      {message && (message.ok ? <InlineSuccess message={message.text} /> : <InlineError message={message.text} />)}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Authority matrix" subtitle="Who may decide each approval level" />
          <table className="w-full text-13">
            <thead>
              <tr className="border-b border-surface-border text-left text-xs text-slate-500">
                <th className="px-4 py-2 font-semibold">Level</th>
                <th className="px-4 py-2 font-semibold">Approver</th>
                <th className="px-4 py-2 text-right font-semibold">Limit</th>
                {isAdmin && <th className="w-px px-4 py-2" />}
              </tr>
            </thead>
            <tbody>
              {assignments.map((a) => (
                <tr key={a.id} className="border-b border-surface-border last:border-0">
                  <td className="px-4 py-2 text-slate-700">{LEVELS.find((l) => l.key === a.level)?.label ?? a.level}</td>
                  <td className="px-4 py-2 font-medium text-slate-900">{a.user_email}</td>
                  <td className="px-4 py-2 text-right tabular">{a.max_amount == null ? "No limit" : formatCurrency(a.max_amount)}</td>
                  {isAdmin && (
                    <td className="px-4 py-2">
                      <button
                        onClick={() => run(`rm-${a.id}`, async () => void (await authorityApi.removeAssignment(a.id)))}
                        className="rounded p-1 text-slate-400 hover:bg-surface-muted hover:text-danger-600"
                        title="Remove assignment"
                      >
                        <UserX className="size-4" />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {isAdmin && (
            <CardBody className="flex flex-wrap items-end gap-2 border-t border-surface-border">
              <select value={level} onChange={(e) => setLevel(e.target.value)} className="field w-auto">
                {LEVELS.map((l) => (
                  <option key={l.key} value={l.key}>{l.label}</option>
                ))}
              </select>
              <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="approver@company.com" className="field w-56" />
              <input value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="Limit (blank = none)" type="number" className="field w-40" />
              <Button
                size="sm"
                icon={<Plus className="size-3.5" />}
                disabled={!email}
                loading={busy === "assign"}
                onClick={() =>
                  run("assign", async () => {
                    await authorityApi.addAssignment(level, email, limit ? Number(limit) : null);
                    setEmail("");
                    setLimit("");
                  })
                }
              >
                Assign
              </Button>
            </CardBody>
          )}
        </Card>

        <Card>
          <CardHeader title="Scenario" />
          <CardBody className="flex flex-col gap-2 text-13 text-slate-600">
            <Button size="sm" variant="secondary" loading={busy === "self"} disabled={!isAdmin} onClick={selfApproval}>
              Try to approve my own request
            </Button>
            <p>
              Raises a ₹3,000 request as you, then tries to approve it — you're an assigned approver for that level,
              so only separation of duties stands in the way. The request is rejected afterwards to clean up.
            </p>
            {!isAdmin && <p className="text-xs">Sign in as admin to run this — admin both raises and approves requests.</p>}
            {scenario && (
              <div className="mt-1 rounded-md border border-surface-border bg-surface-subtle p-2.5">
                <Link to={`/app/requests/${scenario.requestId}`} className="font-medium text-brand-700 hover:underline">
                  PR-{scenario.requestId.slice(0, 8)}
                </Link>
                <p className="mt-1 text-slate-800">{scenario.outcome}</p>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="Delegations" subtitle="Time-boxed hand-over of your approval authority, e.g. while on leave" />
        {(data?.delegations ?? []).length > 0 && (
          <ul className="divide-y divide-surface-border text-13">
            {data!.delegations.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2">
                <span>
                  <span className="font-medium text-slate-900">{d.delegator_email}</span> →{" "}
                  <span className="font-medium text-slate-900">{d.delegate_email}</span>{" "}
                  <span className="text-slate-500">
                    ({LEVELS.find((l) => l.key === d.level)?.label ?? d.level}, until {formatDate(d.valid_until)}) — {d.reason}
                  </span>
                </span>
                <span className="flex items-center gap-2">
                  <StatusDot tone={d.active ? "success" : "neutral"}>{d.active ? "Active" : d.revoked_at ? "Revoked" : "Expired"}</StatusDot>
                  {d.active && (
                    <Button size="sm" variant="ghost" onClick={() => run(`rv-${d.id}`, async () => void (await authorityApi.revokeDelegation(d.id)))}>
                      Revoke
                    </Button>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
        <CardBody className="flex flex-wrap items-end gap-2 border-t border-surface-border">
          <select value={delegLevel} onChange={(e) => setDelegLevel(e.target.value)} className="field w-auto">
            {LEVELS.map((l) => (
              <option key={l.key} value={l.key}>{l.label}</option>
            ))}
          </select>
          <input value={delegate} onChange={(e) => setDelegate(e.target.value)} placeholder="Stand-in's email" className="field w-52" />
          <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="field w-40" />
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason" className="field w-48" />
          <Button
            size="sm"
            disabled={!delegate || !until || reason.length < 3}
            loading={busy === "delegate"}
            onClick={() =>
              run("delegate", async () => {
                await authorityApi.addDelegation({
                  level: delegLevel,
                  delegate_email: delegate,
                  valid_until: new Date(`${until}T23:59:59`).toISOString(),
                  reason,
                });
                setDelegate("");
                setReason("");
                setMessage({ ok: true, text: "Delegation recorded." });
              })
            }
          >
            Delegate my authority
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
