import { useMemo, useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { CheckCircle2, Info, Check, AlertTriangle, ShieldCheck } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { requestsApi, type BulkDecisionItemResult } from "@/api/requests";
import { businessRulesApi } from "@/api/businessRules";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge, StatusBadge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState } from "@/components/ui/ErrorState";
import { FilterChip } from "@/components/ui/FilterChip";
import { PersonName } from "@/components/people/PersonName";
import { APPROVER_ROLES } from "@/lib/constants";
import { formatCountdown, formatCurrency, formatDate, titleCase } from "@/lib/format";
import type { InboxItem, BusinessRule, PurchaseRequest } from "@/types/api";
import { approvalItemPath } from "@/lib/routes";

const DAY_MS = 24 * 3600 * 1000;
const DUE_LABEL: Record<string, string> = { today: "Due within 24 hours", overdue: "Past SLA" };

export function ApprovalInboxPage() {
  usePageHeader("Approval Inbox");
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  // Role scoping default: approver -> dept_manager, finance -> finance_head, admin -> all
  const defaultRole = user?.role === "approver" ? "dept_manager" : user?.role === "finance" ? "finance_head" : "all";
  const role = params.get("role") ?? defaultRole;
  const tab = (params.get("tab") ?? "active") as "active" | "in_progress" | "assigned";
  const due = params.get("due");
  const roles = role === "all" ? APPROVER_ROLES.map((r) => r.value) : [role];

  // Fetch active inbox items for the current role(s)
  const { data: rawInboxItems, loading: inboxLoading, error: inboxError, reload: reloadInbox } = useApi(
    () => Promise.all(roles.map((r) => requestsApi.inbox(r))).then((res) => ({ data: res.flatMap((r) => r.data) })),
    [role],
  );

  // Fetch full requests list to check approval history and populate Assigned / My Approvals tab
  const { data: allRequests, loading: reqLoading, error: reqError, reload: reloadRequests } = useApi(
    () => requestsApi.list(200),
    [],
  );

  const loading = inboxLoading || reqLoading;
  const error = inboxError || reqError;

  const reloadAll = () => {
    reloadInbox();
    reloadRequests();
  };

  // Business Rules for Bulk Approval (Prompt 10 Section 1.1)
  const { data: rulesData } = useApi<Record<string, BusinessRule[]>>(
    () => businessRulesApi.getAll().catch(() => ({ data: {} })),
    [],
  );

  const bulkRules = useMemo(() => {
    const rules = rulesData?.approval ?? [];
    const getVal = (key: string, fallback: any) => {
      const found = rules.find((r: BusinessRule) => r.rule_key === key);
      return found?.current_value != null ? found.current_value : fallback;
    };
    return {
      enabled: Boolean(getVal("approval.bulk_approve_enabled", true)),
      maxAmount: Number(getVal("approval.bulk_approve_max_amount", 25000)),
      maxItems: Number(getVal("approval.bulk_approve_max_items", 25)),
      maxBatchTotal: Number(getVal("approval.bulk_approve_max_batch_total", 250000)),
    };
  }, [rulesData]);

  // Mass selection state (for Active Inbox)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [lastSelectedId, setLastSelectedId] = useState<string | null>(null);
  const [shiftHeld, setShiftHeld] = useState(false);

  // Track shift key for range selection
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === "Shift") setShiftHeld(true); };
    const onKeyUp = (e: KeyboardEvent) => { if (e.key === "Shift") setShiftHeld(false); };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
    };
  }, []);

  // Bulk approval modal state
  const [bulkModalOpen, setBulkModalOpen] = useState(false);
  const [bulkComments, setBulkComments] = useState("Approved in bulk");
  const [acknowledgedAutoSign, setAcknowledgedAutoSign] = useState(false);
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [bulkResults, setBulkResults] = useState<{
    summary: { requested: number; approved: number; skipped: number; total_amount: number };
    items: BulkDecisionItemResult[];
  } | null>(null);

  // Filter Active Inbox: must be actionable by current user and NOT already approved by this user
  const activeItems = useMemo(() => {
    const now = Date.now();
    const me = user?.email?.toLowerCase();

    return (rawInboxItems ?? [])
      .filter((i) => {
        // Exclude if already decided/approved by current user
        const fullReq = allRequests?.find((r) => r.id === i.request_id);
        if (fullReq) {
          if (["approved", "ordered", "partially_received", "fulfilled", "rejected", "cancelled"].includes(fullReq.status ?? "")) {
            return false;
          }
          if (me && fullReq.approval_history?.some((h) => h.decided_by?.toLowerCase() === me && h.decision === "approved")) {
            return false;
          }
        }
        if (!due) return true;
        if (!i.sla_deadline) return false;
        const left = new Date(i.sla_deadline).getTime() - now;
        return due === "overdue" ? left < 0 : left > 0 && left < DAY_MS;
      })
      .sort((a, b) => (a.sla_deadline ?? "9999").localeCompare(b.sla_deadline ?? "9999"));
  }, [rawInboxItems, allRequests, user, due]);

  // Filter in-progress requests: approved by current approver, but still waiting for subsequent approval (e.g. Finance)
  const inProgressItems = useMemo(() => {
    const me = user?.email?.toLowerCase();
    return (allRequests ?? [])
      .filter((r) => {
        if (r.status !== "pending_approval") return false;
        const approvedByMe = r.approval_history?.some(
          (h) => h.decided_by?.toLowerCase() === me && h.decision === "approved"
        );
        if (approvedByMe) return true;
        // Also capture if user is an approver whose tier/step has passed
        if (user?.role === "approver" && r.approval_chain?.includes("dept_manager")) {
          const deptIdx = r.approval_chain.indexOf("dept_manager");
          if (r.current_approver_index > deptIdx) return true;
        }
        return false;
      })
      .sort((a, b) => (b.updated_at ?? b.created_at ?? "").localeCompare(a.updated_at ?? a.created_at ?? ""));
  }, [allRequests, user]);

  // Filter Assigned / All My Approvals: requests where this user made an approval decision or is in chain
  const assignedItems = useMemo(() => {
    const me = user?.email?.toLowerCase();
    return (allRequests ?? [])
      .filter((r) => {
        const decidedByMe = r.approval_history?.some((h) => h.decided_by?.toLowerCase() === me);
        if (decidedByMe) return true;

        if (user?.role === "finance" && r.approval_chain?.includes("finance_head")) {
          return true;
        }
        if (user?.role === "approver" && r.approval_chain?.includes("dept_manager")) {
          return true;
        }
        if (user?.role === "admin" && (r.approval_history?.length ?? 0) > 0) {
          return true;
        }
        return false;
      })
      .sort((a, b) => (b.updated_at ?? b.created_at ?? "").localeCompare(a.updated_at ?? a.created_at ?? ""));
  }, [allRequests, user]);

  // Eligibility check: Prompt 10 Section 1.2
  const checkEligibility = (r: InboxItem): { eligible: boolean; reason?: string } => {
    if (!bulkRules.enabled) return { eligible: false, reason: "Bulk approval is currently disabled" };
    if (r.amount > bulkRules.maxAmount) {
      return { eligible: false, reason: `Above bulk limit of ${formatCurrency(bulkRules.maxAmount, r.currency)}, approve individually` };
    }
    if (r.currency && r.currency !== "INR") {
      return { eligible: false, reason: "Foreign currency requests must be reviewed individually" };
    }
    if (user?.email && r.requested_by === user.email) {
      return { eligible: false, reason: "You requested this (segregation of duties)" };
    }
    return { eligible: true };
  };

  const eligibleRows = useMemo(() => activeItems.filter((r) => checkEligibility(r).eligible), [activeItems, bulkRules, user]);
  const ineligibleCount = activeItems.length - eligibleRows.length;

  const toggleRow = (id: string) => {
    if (shiftHeld && lastSelectedId && activeItems.length > 0) {
      const idx1 = activeItems.findIndex((r) => r.request_id === lastSelectedId);
      const idx2 = activeItems.findIndex((r) => r.request_id === id);
      if (idx1 !== -1 && idx2 !== -1) {
        const start = Math.min(idx1, idx2);
        const end = Math.max(idx1, idx2);
        const next = new Set(selectedIds);
        for (let i = start; i <= end; i++) {
          const row = activeItems[i];
          if (checkEligibility(row).eligible) {
            next.add(row.request_id);
          }
        }
        setSelectedIds(next);
        setLastSelectedId(id);
        return;
      }
    }

    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    setLastSelectedId(id);
  };

  const toggleAll = () => {
    if (selectedIds.size === eligibleRows.length && eligibleRows.length > 0) {
      setSelectedIds(new Set());
    } else {
      const targetRows = eligibleRows.slice(0, bulkRules.maxItems);
      setSelectedIds(new Set(targetRows.map((r) => r.request_id)));
    }
  };

  const isAllSelected = eligibleRows.length > 0 && selectedIds.size === eligibleRows.length;
  const isIndeterminate = selectedIds.size > 0 && !isAllSelected;

  const selectedItems = useMemo(
    () => activeItems.filter((r) => selectedIds.has(r.request_id)),
    [activeItems, selectedIds],
  );

  const totalSelectedAmount = useMemo(
    () => selectedItems.reduce((sum, r) => sum + (r.amount || 0), 0),
    [selectedItems],
  );

  const isCountExceeded = selectedIds.size > bulkRules.maxItems;
  const isTotalExceeded = totalSelectedAmount > bulkRules.maxBatchTotal;
  const capExceededMessage = isCountExceeded
    ? `Only up to ${bulkRules.maxItems} requests can be approved in one batch.`
    : isTotalExceeded
    ? `Total amount exceeds batch cap of ${formatCurrency(bulkRules.maxBatchTotal)}.`
    : null;

  const handleExecuteBulkApprove = async () => {
    if (!user || selectedItems.length === 0 || capExceededMessage) return;
    setBulkProcessing(true);
    setBulkResults(null);

    try {
      const res = await requestsApi.bulkDecision({
        request_ids: Array.from(selectedIds),
        idempotency_key: crypto.randomUUID(),
        comment: bulkComments.trim() || undefined,
        acknowledged_auto_sign: acknowledgedAutoSign,
      });

      setBulkResults({
        summary: {
          requested: res.data.count_requested,
          approved: res.data.count_approved,
          skipped: res.data.count_skipped,
          total_amount: res.data.total_approved_amount,
        },
        items: res.data.items || [],
      });

      reloadAll();
    } catch (e: any) {
      setBulkResults({
        summary: { requested: selectedIds.size, approved: 0, skipped: selectedIds.size, total_amount: 0 },
        items: [
          {
            request_id: "batch",
            result: "failed",
            reason_code: "error",
            message: e?.message || "Bulk decision execution failed.",
          },
        ],
      });
    } finally {
      setBulkProcessing(false);
    }
  };

  const setTab = (k: string) => {
    const next = new URLSearchParams(params);
    if (k === "active") next.delete("tab");
    else next.set("tab", k);
    setParams(next, { replace: true });
    setSelectedIds(new Set());
    setLastSelectedId(null);
  };

  const setRole = (k: string) => {
    const next = new URLSearchParams(params);
    if (k === defaultRole) next.delete("role");
    else next.set("role", k);
    setParams(next, { replace: true });
    setSelectedIds(new Set());
    setLastSelectedId(null);
  };

  const clearDue = () => {
    const next = new URLSearchParams(params);
    next.delete("due");
    setParams(next, { replace: true });
  };

  const activeColumns: Column<InboxItem>[] = [
    {
      key: "id",
      header: "Request",
      render: (r) => (
        <span className="font-mono text-caption text-ink-2">PR-{r.request_id.slice(0, 8)}</span>
      ),
    },
    { key: "requester", header: "Requester", render: (r) => <PersonName email={r.requested_by} /> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type) },
    { key: "dept", header: "Department", render: (r) => r.department },
    {
      key: "amount",
      header: "Amount",
      render: (r) => {
        const check = checkEligibility(r);
        return (
          <div className="flex flex-col items-end">
            <span className="tabular font-medium">{formatCurrency(r.amount, r.currency)}</span>
            {!check.eligible && (
              <span
                className="mt-0.5 inline-block text-[11px] font-medium text-amber-700 bg-amber-50 px-1 py-0.2 rounded border border-amber-200"
                title={check.reason}
              >
                Individual only
              </span>
            )}
          </div>
        );
      },
      sortValue: (r) => r.amount,
      className: "text-right",
    },
    { key: "tier", header: "Tier", render: (r) => <span className="text-ink-2">{titleCase(r.spend_tier)}</span> },
    { key: "submitted", header: "Submitted", render: (r) => formatDate(r.created_at) },
    {
      key: "sla",
      header: "SLA",
      render: (r) => {
        const countdown = formatCountdown(r.sla_deadline);
        if (!countdown) return "—";
        return <Badge tone={countdown.overdue ? "danger" : "warning"}>{countdown.label}</Badge>;
      },
      sortValue: (r) => r.sla_deadline ?? "9999",
    },
  ];

  const inProgressColumns: Column<PurchaseRequest>[] = [
    {
      key: "id",
      header: "Request",
      render: (r) => <span className="font-mono text-xs">PR-{r.id.slice(0, 8)}</span>,
    },
    { key: "requester", header: "Requester", render: (r) => <PersonName email={r.requested_by} /> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type) },
    { key: "dept", header: "Department", render: (r) => r.department ?? "—" },
    {
      key: "amount",
      header: "Amount",
      render: (r) => <span className="tabular font-medium">{formatCurrency(r.amount, r.currency ?? "INR")}</span>,
      sortValue: (r) => r.amount ?? 0,
    },
    {
      key: "current_level",
      header: "Current Approver",
      render: (r) => {
        const chain = r.approval_chain || [];
        const currentLevel = chain[r.current_approver_index];
        const label = currentLevel === "finance_head" ? "Finance Head" : currentLevel ? titleCase(currentLevel) : "Next Approver";
        return (
          <Badge tone="warning">
            Awaiting {label}
          </Badge>
        );
      },
    },
    {
      key: "my_action",
      header: "Your Action",
      render: (r) => {
        const me = user?.email?.toLowerCase();
        const myDecision = r.approval_history?.find((h) => h.decided_by?.toLowerCase() === me && h.decision === "approved");
        return (
          <span className="inline-flex items-center gap-1.5 text-xs text-success font-medium">
            <CheckCircle2 className="size-3.5" />
            <span>Approved {myDecision?.decided_at ? `(${formatDate(myDecision.decided_at)})` : ""}</span>
          </span>
        );
      },
    },
    {
      key: "submitted",
      header: "Submitted",
      render: (r) => formatDate(r.created_at),
      sortValue: (r) => r.created_at ?? "",
    },
  ];

  const assignedColumns: Column<PurchaseRequest>[] = [
    {
      key: "id",
      header: "Request",
      render: (r) => <span className="font-mono text-xs">PR-{r.id.slice(0, 8)}</span>,
    },
    { key: "requester", header: "Requester", render: (r) => <PersonName email={r.requested_by} /> },
    { key: "type", header: "Type", render: (r) => titleCase(r.request_type) },
    { key: "dept", header: "Department", render: (r) => r.department ?? "—" },
    {
      key: "amount",
      header: "Amount",
      render: (r) => <span className="tabular font-medium">{formatCurrency(r.amount, r.currency ?? "INR")}</span>,
      sortValue: (r) => r.amount ?? 0,
    },
    {
      key: "status",
      header: "Lifecycle Status",
      render: (r) => {
        if (r.status === "pending_approval") {
          const chain = r.approval_chain || [];
          const currentLevel = chain[r.current_approver_index];
          const levelName = currentLevel === "finance_head" ? "Finance Head" : currentLevel === "dept_manager" ? "Dept Manager" : currentLevel ? titleCase(currentLevel) : "Approver";
          return (
            <span className="inline-flex items-center gap-1.5">
              <StatusBadge status="pending_approval" />
              <span className="text-xs text-amber-700 font-medium">({levelName})</span>
            </span>
          );
        }
        return <StatusBadge status={r.status} />;
      },
    },
    {
      key: "my_action",
      header: "Your Action",
      render: (r) => {
        const myDecision = r.approval_history?.find((h) => h.decided_by?.toLowerCase() === user?.email?.toLowerCase());
        if (myDecision) {
          return (
            <span className="inline-flex items-center gap-1.5 text-xs text-ink-2">
              <CheckCircle2 className="size-3.5 text-success" />
              <span>{titleCase(myDecision.decision)} ({formatDate(myDecision.decided_at ?? r.updated_at)})</span>
            </span>
          );
        }
        return <span className="text-xs text-ink-3">Assigned in workflow</span>;
      },
    },
    {
      key: "submitted",
      header: "Submitted",
      render: (r) => formatDate(r.created_at),
      sortValue: (r) => r.created_at ?? "",
    },
  ];

  if (error) return <ErrorState message={error} onRetry={reloadAll} />;

  return (
    <div className="flex flex-col gap-4">
      {/* Primary Navigation Tabs: Active Inbox vs Awaiting Finance / In Progress vs All My Approvals */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          tabs={[
            { key: "active", label: `Active Inbox (${activeItems.length})` },
            ...(user?.role === "approver" || user?.role === "admin"
              ? [{ key: "in_progress", label: `${user?.role === "approver" ? "Awaiting Finance" : "In Progress"} (${inProgressItems.length})` }]
              : []),
            { key: "assigned", label: `All My Approvals (${assignedItems.length})` },
          ]}
          active={tab}
          onChange={setTab}
        />
      </div>

      {tab === "active" && (
        <>
          {/* Helpful callout if active inbox is clear but in-progress approvals are pending next level */}
          {inProgressItems.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-accent-soft bg-accent-tint/30 px-3.5 py-2.5 text-xs text-ink">
              <div className="flex items-center gap-2">
                <Info className="size-4 shrink-0 text-accent" />
                <span>
                  You have <strong>{inProgressItems.length}</strong> request{inProgressItems.length > 1 ? "s" : ""} approved by you currently awaiting Finance approval.
                </span>
              </div>
              <Button size="sm" variant="secondary" onClick={() => setTab("in_progress")}>
                View {user?.role === "approver" ? "Awaiting Finance" : "In Progress"} ({inProgressItems.length})
              </Button>
            </div>
          )}

          {due && DUE_LABEL[due] && (
            <div>
              <FilterChip label={DUE_LABEL[due]} onClear={clearDue} />
            </div>
          )}

          {/* Sticky Bulk Action Toolbar */}
          {selectedIds.size > 0 && (
            <div className="sticky top-2 z-20 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent-soft bg-sheet px-4 py-2.5 shadow-md backdrop-blur">
              <div className="flex items-center gap-3 text-sm text-ink font-medium">
                <span className="inline-flex size-6 items-center justify-center rounded-full bg-accent text-xs font-semibold text-white">
                  {selectedIds.size}
                </span>
                <span>selected</span>
                <span className="text-xs text-ink-3">
                  ({formatCurrency(totalSelectedAmount)} of {formatCurrency(bulkRules.maxBatchTotal)} limit)
                </span>
                {capExceededMessage && (
                  <span className="inline-flex items-center gap-1 text-xs text-danger font-normal">
                    <AlertTriangle className="size-3.5" />
                    {capExceededMessage}
                  </span>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setSelectedIds(new Set());
                    setLastSelectedId(null);
                  }}
                >
                  Clear selection
                </Button>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={Boolean(capExceededMessage)}
                  onClick={() => {
                    setBulkResults(null);
                    setAcknowledgedAutoSign(false);
                    setBulkModalOpen(true);
                  }}
                >
                  <Check className="mr-1.5 size-4" />
                  Approve ({selectedIds.size})
                </Button>
              </div>
            </div>
          )}

          {/* Gmail-style select-all banner */}
          {selectedIds.size > 0 && selectedIds.size < eligibleRows.length && eligibleRows.length <= bulkRules.maxItems && (
            <div className="flex items-center justify-between rounded border border-accent-soft bg-accent-tint/40 px-3.5 py-1.5 text-xs text-ink">
              <span>
                {selectedIds.size} eligible on this page selected.
              </span>
              <button
                type="button"
                onClick={() => setSelectedIds(new Set(eligibleRows.map((r) => r.request_id)))}
                className="font-semibold text-accent hover:underline ml-2"
              >
                Select all {eligibleRows.length} eligible matching this filter
              </button>
            </div>
          )}
          {eligibleRows.length > bulkRules.maxItems && selectedIds.size >= bulkRules.maxItems && (
            <div className="rounded border border-amber-200 bg-amber-50 px-3.5 py-1.5 text-xs text-amber-900">
              Only the first {bulkRules.maxItems} requests can be approved at once.
            </div>
          )}

          {/* Policy Notice if any items require individual review */}
          {ineligibleCount > 0 && (
            <div className="flex items-center gap-2 rounded border border-rule bg-sheet px-3.5 py-2 text-xs text-ink-2">
              <Info className="size-4 shrink-0 text-accent" />
              <span>
                {ineligibleCount} request{ineligibleCount > 1 ? "s" : ""} exceed{ineligibleCount === 1 ? "s" : ""} the bulk threshold of <strong>{formatCurrency(bulkRules.maxAmount)}</strong> and must be reviewed and approved individually.
              </span>
            </div>
          )}

          <Card>
            {/* Secondary Role Selector for Admins or multi-role inspection */}
            <div className="px-2 pt-1 sm:px-3">
              <Tabs
                tabs={[{ key: "all", label: "All roles" }, ...APPROVER_ROLES.map((r) => ({ key: r.value, label: r.label }))]}
                active={role}
                onChange={setRole}
              />
            </div>
            <CardBody>
              <DataTable
                columns={activeColumns}
                rows={activeItems}
                rowKey={(r) => r.request_id}
                loading={loading}
                onRowClick={(r) => navigate(approvalItemPath(r))}
                emptyTitle="Nothing waiting for a decision"
                selectable={{
                  selectedKeys: selectedIds,
                  onToggleRow: toggleRow,
                  onToggleAll: toggleAll,
                  isAllSelected,
                  isIndeterminate,
                  isRowSelectable: (r) => checkEligibility(r).eligible,
                  disabledReason: (r) => checkEligibility(r).reason,
                }}
              />
            </CardBody>
          </Card>
        </>
      )}

      {tab === "in_progress" && (
        <Card>
          <CardBody>
            <DataTable
              columns={inProgressColumns}
              rows={inProgressItems}
              rowKey={(r) => r.id}
              loading={loading}
              onRowClick={(r) => navigate(approvalItemPath({ request_id: r.id }))}
              emptyTitle="No requests currently awaiting subsequent approval"
            />
          </CardBody>
        </Card>
      )}

      {tab === "assigned" && (
        <Card>
          <CardBody>
            <DataTable
              columns={assignedColumns}
              rows={assignedItems}
              rowKey={(r) => r.id}
              loading={loading}
              onRowClick={(r) => navigate(approvalItemPath({ request_id: r.id }))}
              emptyTitle="No assigned or previously approved requests found"
            />
          </CardBody>
        </Card>
      )}

      {/* Bulk Approval Confirmation Modal */}
      {bulkModalOpen && (
        <Modal
          open={bulkModalOpen}
          onClose={() => !bulkProcessing && setBulkModalOpen(false)}
          title={bulkResults ? "Bulk Approval Results" : `Approve ${selectedItems.length} Purchase Requests`}
          size="md"
          footer={
            <div className="flex w-full items-center justify-end gap-2">
              {bulkResults ? (
                <Button
                  variant="primary"
                  onClick={() => {
                    setSelectedIds(new Set());
                    setBulkModalOpen(false);
                    setBulkResults(null);
                  }}
                >
                  Done
                </Button>
              ) : (
                <>
                  <Button
                    variant="secondary"
                    disabled={bulkProcessing}
                    onClick={() => setBulkModalOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="primary"
                    loading={bulkProcessing}
                    disabled={bulkProcessing || (user?.role === "finance" && !acknowledgedAutoSign)}
                    onClick={handleExecuteBulkApprove}
                  >
                    <Check className="mr-1.5 size-4" />
                    Confirm & Approve ({selectedItems.length})
                  </Button>
                </>
              )}
            </div>
          }
        >
          {bulkResults ? (
            <div className="flex flex-col gap-4 text-sm">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="rounded bg-emerald-50 border border-emerald-200 p-2.5">
                  <span className="text-xs text-emerald-800 block">Approved</span>
                  <span className="text-xl font-bold text-emerald-900">{bulkResults.summary.approved}</span>
                </div>
                <div className="rounded bg-amber-50 border border-amber-200 p-2.5">
                  <span className="text-xs text-amber-800 block">Skipped</span>
                  <span className="text-xl font-bold text-amber-900">{bulkResults.summary.skipped}</span>
                </div>
                <div className="rounded bg-sheet-sunk border border-rule p-2.5">
                  <span className="text-xs text-ink-3 block">Total Approved</span>
                  <span className="text-sm font-semibold text-ink">{formatCurrency(bulkResults.summary.total_amount)}</span>
                </div>
              </div>

              <div className="max-h-60 overflow-y-auto divide-y divide-rule border-y border-rule text-xs">
                {bulkResults.items.map((it, idx) => (
                  <div key={idx} className="flex items-center justify-between py-2">
                    <span className="font-mono">PR-{it.request_id.slice(0, 8)}</span>
                    <div className="flex items-center gap-2">
                      <Badge tone={it.result === "approved" ? "success" : it.result === "skipped" ? "warning" : "danger"}>
                        {it.result}
                      </Badge>
                      {it.reason_code && <span className="text-ink-3">{it.reason_code}</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4 text-sm">
              <p className="text-ink-2">
                You are about to batch-approve <strong>{selectedItems.length}</strong> purchase requests totaling <strong>{formatCurrency(totalSelectedAmount)}</strong>.
              </p>

              {user?.role === "finance" && (
                <div className="rounded-lg border border-accent/30 bg-accent-tint/40 p-3.5 text-xs text-ink flex flex-col gap-2.5">
                  <div className="flex items-center gap-2 font-medium">
                    <ShieldCheck className="size-4 text-accent" />
                    <span>Standing Mandate Automated Signing</span>
                  </div>
                  <p className="text-ink-2">
                    Under your active signing authority, eligible contracts will be automatically signed under your name. Requests exceeding your limit or with uncleared vendors will require individual review.
                  </p>
                  <label className="flex items-start gap-2 pt-1 cursor-pointer font-medium text-ink">
                    <input
                      type="checkbox"
                      checked={acknowledgedAutoSign}
                      onChange={(e) => setAcknowledgedAutoSign(e.target.checked)}
                      className="mt-0.5 size-4 rounded border-rule-strong text-accent focus:ring-accent"
                    />
                    <span>I acknowledge that eligible contracts will be automatically signed under my standing mandate.</span>
                  </label>
                </div>
              )}

              <div>
                <label className="mb-1 block text-xs font-medium text-ink-2">Approval Comments (Optional)</label>
                <textarea
                  value={bulkComments}
                  onChange={(e) => setBulkComments(e.target.value)}
                  disabled={bulkProcessing}
                  rows={2}
                  className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
                  placeholder="Comments applied to all selected requests..."
                />
              </div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
