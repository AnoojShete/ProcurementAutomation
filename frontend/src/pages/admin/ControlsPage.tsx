import { useSearchParams } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { opsApi } from "@/api/controls";
import { Tabs } from "@/components/ui/Tabs";
import { ReliabilityPanel } from "@/components/controls/ReliabilityPanel";
import { AuthorityPanel } from "@/components/controls/AuthorityPanel";
import { PaymentPanel } from "@/components/controls/PaymentPanel";
import { LedgerPanel } from "@/components/controls/LedgerPanel";
import { LearningPanel } from "@/components/controls/LearningPanel";

const TABS = [
  { key: "reliability", label: "Event reliability" },
  { key: "authority", label: "Approval authority" },
  { key: "payments", label: "Payment protection" },
  { key: "matching", label: "Invoice matching" },
  { key: "learning", label: "Learning" },
];

/** The platform's controls in one place: live state for operators, and
 * scenario buttons that exercise each control end to end for demos. */
export function ControlsPage() {
  usePageHeader("Controls");
  const [params, setParams] = useSearchParams();
  const active = params.get("tab") ?? "reliability";
  // Scenario buttons call demo-only endpoints, enabled when the stack runs
  // with APP_SHOWCASE_MODE on (the default for demo environments).
  const { data: eventing } = useApi(() => opsApi.eventing(), []);
  const dlqOpen = Object.values(eventing?.dlq ?? {}).reduce((n, s) => n + (s.open ?? 0), 0);
  const showcase = eventing?.showcase_mode ?? false;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-slate-600">
        Safeguards that keep procurement data correct and payments safe. Each tab shows the live state and a scenario that
        exercises the control against the running system.
      </p>
      <Tabs
        tabs={TABS.map((t) => (t.key === "reliability" && dlqOpen ? { ...t, count: dlqOpen } : t))}
        active={active}
        onChange={(k) => setParams({ tab: k }, { replace: true })}
      />
      {active === "reliability" && <ReliabilityPanel showcase={showcase} />}
      {active === "authority" && <AuthorityPanel />}
      {active === "payments" && <PaymentPanel showcase={showcase} />}
      {active === "matching" && <LedgerPanel />}
      {active === "learning" && <LearningPanel showcase={showcase} />}
    </div>
  );
}
