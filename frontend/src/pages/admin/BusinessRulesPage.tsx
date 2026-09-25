import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import {
  Sliders,
  RotateCcw,
  Edit3,
  ExternalLink,
  History,
  CheckCircle2,
  AlertTriangle,
  Plus,
  Trash2,
  Search,
  Filter,
  ArrowRight,
  Sparkles,
} from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { businessRulesApi, type HistoryFilterParams } from "@/api/businessRules";
import type { BusinessRule, BusinessRuleHistory, SpendTierItem } from "@/types/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState, InlineInfo } from "@/components/ui/ErrorState";
import { formatDateTime } from "@/lib/format";

const CATEGORY_TABS = [
  { key: "approval", label: "Approval" },
  { key: "budget", label: "Budget" },
  { key: "vendor_verification", label: "Vendor Verification" },
  { key: "license_usage", label: "License Usage" },
  { key: "risk_compliance", label: "Risk & Compliance" },
  { key: "history", label: "Change History" },
];

const APPROVER_ROLES = ["manager", "finance", "director", "vp", "cfo"];

const VALUE_TYPE_BADGES: Record<string, { label: string; tone: "brand" | "intel" | "warning" | "neutral" | "success" }> = {
  currency: { label: "Currency ($)", tone: "brand" },
  integer: { label: "Integer", tone: "intel" },
  float: { label: "Float", tone: "intel" },
  percentage: { label: "Percentage (%)", tone: "warning" },
  days: { label: "Days", tone: "neutral" },
  hours: { label: "Hours", tone: "neutral" },
  boolean: { label: "Boolean", tone: "success" },
  json: { label: "JSON / Table", tone: "brand" },
};

export function BusinessRulesPage() {
  usePageHeader("Business Rules");

  const [activeTab, setActiveTab] = useState("approval");
  const [rulesGrouped, setRulesGrouped] = useState<Record<string, BusinessRule[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Search in active rules tab
  const [searchQuery, setSearchQuery] = useState("");

  // History state
  const [historyItems, setHistoryItems] = useState<BusinessRuleHistory[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<HistoryFilterParams>({ limit: 50, offset: 0 });

  // Edit Modal State
  const [editingRule, setEditingRule] = useState<BusinessRule | null>(null);
  const [editValue, setEditValue] = useState<any>(null);
  const [editJustification, setEditJustification] = useState("");
  const [editSaving, setEditSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Reset Modal State
  const [resettingRule, setResettingRule] = useState<BusinessRule | null>(null);
  const [resetJustification, setResetJustification] = useState("");
  const [resetSaving, setResetSaving] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);

  const fetchRules = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await businessRulesApi.getAll();
      setRulesGrouped(res.data);
    } catch (err: any) {
      setError(err?.message || "Failed to load business rules");
    } finally {
      setLoading(false);
    }
  };

  const fetchHistory = async (params: HistoryFilterParams = historyFilter) => {
    try {
      setHistoryLoading(true);
      const res = await businessRulesApi.getHistory(params);
      setHistoryItems(res.data || []);
    } catch (err: any) {
      console.error("Failed to load history", err);
    } finally {
      setHistoryLoading(false);
    }
  };

  useEffect(() => {
    void fetchRules();
  }, []);

  useEffect(() => {
    if (activeTab === "history") {
      void fetchHistory();
    }
  }, [activeTab]);

  // Open Edit modal
  const handleStartEdit = (rule: BusinessRule) => {
    setEditingRule(rule);
    setEditValue(JSON.parse(JSON.stringify(rule.current_value)));
    setEditJustification("");
    setEditError(null);
  };

  // Open Reset modal
  const handleStartReset = (rule: BusinessRule) => {
    setResettingRule(rule);
    setResetJustification("");
    setResetError(null);
  };

  // Submit Edit
  const handleSaveEdit = async () => {
    if (!editingRule) return;
    if (editJustification.trim().length < 10) {
      setEditError("Justification must be at least 10 characters long.");
      return;
    }

    try {
      setEditSaving(true);
      setEditError(null);
      await businessRulesApi.updateRule(editingRule.rule_key, editValue, editJustification.trim());
      setEditingRule(null);
      await fetchRules();
    } catch (err: any) {
      setEditError(err?.message || "Failed to update business rule");
    } finally {
      setEditSaving(false);
    }
  };

  // Submit Reset
  const handleSaveReset = async () => {
    if (!resettingRule) return;
    if (resetJustification.trim().length < 10) {
      setResetError("Justification must be at least 10 characters long.");
      return;
    }

    try {
      setResetSaving(true);
      setResetError(null);
      await businessRulesApi.resetRule(resettingRule.rule_key, resetJustification.trim());
      setResettingRule(null);
      await fetchRules();
    } catch (err: any) {
      setResetError(err?.message || "Failed to reset rule");
    } finally {
      setResetSaving(false);
    }
  };

  // Filter current tab rules
  const currentCategoryRules = useMemo(() => {
    const list = rulesGrouped[activeTab] || [];
    if (!searchQuery.trim()) return list;
    const q = searchQuery.toLowerCase();
    return list.filter(
      (r) =>
        r.rule_key.toLowerCase().includes(q) ||
        r.display_name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q),
    );
  }, [rulesGrouped, activeTab, searchQuery]);

  // Format rule value for display
  const formatRuleValue = (rule: BusinessRule) => {
    const val = rule.current_value;
    if (val === null || val === undefined) return "None";

    if (rule.value_type === "currency") {
      return `$${Number(val).toLocaleString()}`;
    }
    if (rule.value_type === "percentage") {
      const num = Number(val);
      return num <= 1 ? `${Math.round(num * 100)}%` : `${num}%`;
    }
    if (rule.value_type === "days") {
      if (Array.isArray(val)) return val.map((v) => `${v}d`).join(", ");
      return `${val} days`;
    }
    if (rule.value_type === "hours") {
      if (typeof val === "object" && !Array.isArray(val)) {
        return Object.entries(val)
          .map(([k, v]) => `${k}: ${v}h`)
          .join(" | ");
      }
      return `${val} hours`;
    }
    if (rule.value_type === "boolean") {
      return val ? "True (Enabled)" : "False (Disabled)";
    }
    if (rule.rule_key === "approval.spend_tiers" && Array.isArray(val)) {
      return `${val.length} configured tiers (${val.map((t: any) => t.tier_name).join(" → ")})`;
    }
    if (typeof val === "object") {
      return JSON.stringify(val);
    }
    return String(val);
  };

  // Validation logic for Edit Modal
  const isEditValid = useMemo(() => {
    if (!editingRule) return false;
    if (editJustification.trim().length < 10) return false;

    // Check bounds for numeric types
    if (typeof editValue === "number") {
      if (editingRule.min_value !== null && editValue < editingRule.min_value) return false;
      if (editingRule.max_value !== null && editValue > editingRule.max_value) return false;
    }

    // Check spend tiers
    if (editingRule.rule_key === "approval.spend_tiers") {
      if (!Array.isArray(editValue) || editValue.length === 0) return false;
      for (let i = 0; i < editValue.length; i++) {
        const tier = editValue[i];
        if (!tier.tier_name || !tier.tier_name.trim()) return false;
        if (typeof tier.min_amount !== "number" || tier.min_amount < 0) return false;
        if (!Array.isArray(tier.required_approvers) || tier.required_approvers.length === 0) return false;
        if (typeof tier.sla_hours !== "number" || tier.sla_hours <= 0) return false;
        if (i > 0) {
          const prev = editValue[i - 1];
          if (prev.max_amount !== tier.min_amount) return false; // Gap or overlap
        }
        if (tier.max_amount !== null && tier.max_amount <= tier.min_amount) return false;
      }
    }

    // Unchanged value check
    if (JSON.stringify(editValue) === JSON.stringify(editingRule.current_value)) {
      return false;
    }

    return true;
  }, [editingRule, editValue, editJustification]);

  return (
    <div className="flex flex-col gap-6">
      {/* Top Banner: Link to Live Verification Mode */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-200 bg-gradient-to-r from-brand-50 to-intel-50 px-5 py-4 text-brand-900 shadow-sm">
        <div className="flex items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
            <Sparkles className="size-5" />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900">Live Registry Verification Mode</p>
            <p className="text-xs text-slate-600">
              Looking to toggle real registry calls? Manage Live Verification Mode & quotas in System Health →
            </p>
          </div>
        </div>
        <Link
          to="/app/system-health"
          className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-2 text-xs font-semibold text-brand-700 shadow-sm ring-1 ring-inset ring-brand-300 hover:bg-brand-50 hover:text-brand-900 transition-colors"
        >
          Manage Live Mode in System Health
          <ArrowRight className="size-3.5" />
        </Link>
      </div>

      {/* Main Tabs */}
      <Card>
        <CardHeader
          title="Business Rules Configuration"
          subtitle="Inspect and fine-tune operational parameters, spend tiers, SLAs, and fraud tolerance across all services."
        />
        <div className="px-5 pt-2">
          <Tabs tabs={CATEGORY_TABS} active={activeTab} onChange={(k) => { setActiveTab(k); setSearchQuery(""); }} />
        </div>

        <CardBody>
          {loading ? (
            <div className="flex h-48 items-center justify-center">
              <div className="size-6 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={fetchRules} />
          ) : activeTab === "history" ? (
            /* History Feed Tab */
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-3 rounded-lg bg-surface-subtle p-3 text-xs">
                <Filter className="size-4 text-slate-500" />
                <input
                  type="text"
                  placeholder="Filter by rule key..."
                  value={historyFilter.rule_key || ""}
                  onChange={(e) => setHistoryFilter({ ...historyFilter, rule_key: e.target.value || undefined })}
                  className="rounded-md border border-surface-border bg-white px-2.5 py-1.5 text-xs text-slate-800 shadow-sm"
                />
                <input
                  type="text"
                  placeholder="Changed by (user / email)..."
                  value={historyFilter.changed_by || ""}
                  onChange={(e) => setHistoryFilter({ ...historyFilter, changed_by: e.target.value || undefined })}
                  className="rounded-md border border-surface-border bg-white px-2.5 py-1.5 text-xs text-slate-800 shadow-sm"
                />
                <select
                  value={historyFilter.category || ""}
                  onChange={(e) => setHistoryFilter({ ...historyFilter, category: e.target.value || undefined })}
                  className="rounded-md border border-surface-border bg-white px-2.5 py-1.5 text-xs text-slate-800 shadow-sm"
                >
                  <option value="">All Categories</option>
                  <option value="approval">Approval</option>
                  <option value="budget">Budget</option>
                  <option value="vendor_verification">Vendor Verification</option>
                  <option value="license_usage">License Usage</option>
                  <option value="risk_compliance">Risk & Compliance</option>
                </select>
                <Button size="sm" variant="secondary" onClick={() => void fetchHistory()}>
                  Apply Filters
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const reset = { limit: 50, offset: 0 };
                    setHistoryFilter(reset);
                    void fetchHistory(reset);
                  }}
                >
                  Reset
                </Button>
              </div>

              {historyLoading ? (
                <div className="flex h-32 items-center justify-center">
                  <div className="size-5 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
                </div>
              ) : historyItems.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">No rule modification history recorded yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="border-b border-surface-border bg-surface-subtle font-semibold text-slate-600 uppercase">
                      <tr>
                        <th className="py-2.5 px-3">Rule Key</th>
                        <th className="py-2.5 px-3">Changed At</th>
                        <th className="py-2.5 px-3">Changed By</th>
                        <th className="py-2.5 px-3">Old Value</th>
                        <th className="py-2.5 px-3">New Value</th>
                        <th className="py-2.5 px-3">Justification</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-border">
                      {historyItems.map((item) => (
                        <tr key={item.id} className="hover:bg-slate-50">
                          <td className="py-2.5 px-3 font-mono font-medium text-slate-900">{item.rule_key}</td>
                          <td className="py-2.5 px-3 whitespace-nowrap text-slate-500">{formatDateTime(item.changed_at)}</td>
                          <td className="py-2.5 px-3 text-slate-700">{item.changed_by}</td>
                          <td className="py-2.5 px-3 font-mono text-slate-600 max-w-44 truncate" title={JSON.stringify(item.old_value)}>
                            {JSON.stringify(item.old_value)}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-brand-700 max-w-44 truncate" title={JSON.stringify(item.new_value)}>
                            {JSON.stringify(item.new_value)}
                          </td>
                          <td className="py-2.5 px-3 italic text-slate-700 max-w-xs">{item.justification}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ) : (
            /* Rules List for Category */
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between gap-4">
                <div className="relative max-w-sm flex-1">
                  <Search className="absolute left-2.5 top-2.5 size-4 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search rules in this section..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full rounded-lg border border-surface-border bg-white pl-9 pr-3 py-1.5 text-xs text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none"
                  />
                </div>
                <span className="text-xs text-slate-500">
                  Showing {currentCategoryRules.length} rule{currentCategoryRules.length !== 1 ? "s" : ""}
                </span>
              </div>

              {currentCategoryRules.length === 0 ? (
                <p className="py-8 text-center text-sm text-slate-500">No matching rules found in this category.</p>
              ) : (
                <div className="grid grid-cols-1 gap-4">
                  {currentCategoryRules.map((rule) => {
                    const badgeInfo = VALUE_TYPE_BADGES[rule.value_type] || { label: rule.value_type, tone: "neutral" as const };
                    const isDefault = JSON.stringify(rule.current_value) === JSON.stringify(rule.default_value);

                    return (
                      <div
                        key={rule.rule_key}
                        className="flex flex-col justify-between rounded-xl border border-surface-border bg-white p-4 shadow-subtle hover:border-slate-300 transition-all sm:flex-row sm:items-center gap-4"
                      >
                        <div className="flex-1 min-w-0">
                          <div className="flex flex-wrap items-center gap-2 mb-1">
                            <h3 className="text-sm font-semibold text-slate-900">{rule.display_name}</h3>
                            <Badge tone={badgeInfo.tone}>{badgeInfo.label}</Badge>
                            {isDefault ? (
                              <span className="text-[11px] font-medium text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full">
                                Default
                              </span>
                            ) : (
                              <span className="text-[11px] font-medium text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
                                Modified
                              </span>
                            )}
                          </div>
                          <p className="font-mono text-xs text-slate-500 mb-1">{rule.rule_key}</p>
                          <p className="text-xs text-slate-600 mb-2">{rule.description}</p>

                          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
                            <div>
                              <span className="font-medium text-slate-700">Current Value: </span>
                              <span className="font-semibold text-slate-900">{formatRuleValue(rule)}</span>
                            </div>
                            <div className="text-slate-400">•</div>
                            <div>
                              <span>Default: </span>
                              <span className="font-mono text-slate-600">
                                {typeof rule.default_value === "object"
                                  ? JSON.stringify(rule.default_value)
                                  : String(rule.default_value)}
                              </span>
                            </div>
                            {rule.updated_at && (
                              <>
                                <div className="text-slate-400">•</div>
                                <div>
                                  <span>Updated: </span>
                                  <span>{formatDateTime(rule.updated_at)}</span>
                                </div>
                              </>
                            )}
                          </div>
                        </div>

                        <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                          <Button
                            size="sm"
                            variant="secondary"
                            icon={<Edit3 className="size-3.5" />}
                            onClick={() => handleStartEdit(rule)}
                          >
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={isDefault}
                            icon={<RotateCcw className="size-3.5" />}
                            onClick={() => handleStartReset(rule)}
                            title={isDefault ? "Rule is already at default value" : "Reset to system default"}
                          >
                            Reset
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Edit Rule Modal */}
      {editingRule && (
        <Modal
          open={!!editingRule}
          onClose={() => setEditingRule(null)}
          title={`Edit Rule: ${editingRule.display_name}`}
          size={editingRule.rule_key === "approval.spend_tiers" ? "lg" : "md"}
          footer={
            <div className="flex items-center justify-between w-full">
              <span className="text-xs text-slate-500">
                {editJustification.trim().length < 10
                  ? `Need ${10 - editJustification.trim().length} more character${10 - editJustification.trim().length === 1 ? "" : "s"} for justification`
                  : "✓ Justification requirement satisfied"}
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setEditingRule(null)} disabled={editSaving}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={() => void handleSaveEdit()} loading={editSaving} disabled={!isEditValid}>
                  Save Rule Changes
                </Button>
              </div>
            </div>
          }
        >
          <div className="flex flex-col gap-4 py-2">
            <div>
              <p className="font-mono text-xs text-slate-500">{editingRule.rule_key}</p>
              <p className="text-xs text-slate-600 mt-1">{editingRule.description}</p>
            </div>

            {editError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-xs text-rose-700">
                {editError}
              </div>
            )}

            {/* Type-specific Value Input */}
            <div className="rounded-lg border border-surface-border bg-surface-subtle p-3">
              <label className="block text-xs font-semibold text-slate-700 mb-1">Configured Value</label>

              {editingRule.rule_key === "approval.spend_tiers" ? (
                /* Spend Tiers Dedicated Table Editor */
                <SpendTiersEditor tiers={editValue as SpendTierItem[]} onChange={(updated) => setEditValue(updated)} />
              ) : editingRule.value_type === "boolean" ? (
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setEditValue(!editValue)}
                    className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${
                      editValue ? "bg-brand-600" : "bg-slate-300"
                    }`}
                  >
                    <span
                      className={`inline-block size-5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                        editValue ? "translate-x-5" : "translate-x-0"
                      }`}
                    />
                  </button>
                  <span className="text-sm font-medium text-slate-800">
                    {editValue ? "Enabled (True)" : "Disabled (False)"}
                  </span>
                </div>
              ) : editingRule.value_type === "currency" ? (
                <div className="relative">
                  <span className="absolute left-3 top-2 text-sm text-slate-500">$</span>
                  <input
                    type="number"
                    step="1"
                    min={editingRule.min_value ?? 0}
                    max={editingRule.max_value ?? undefined}
                    value={editValue}
                    onChange={(e) => setEditValue(parseFloat(e.target.value) || 0)}
                    className="w-full rounded-md border border-surface-border bg-white pl-7 pr-3 py-1.5 text-sm text-slate-800 shadow-sm"
                  />
                  {editingRule.min_value !== null && editingRule.max_value !== null && (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Allowed range: ${editingRule.min_value.toLocaleString()} – ${editingRule.max_value.toLocaleString()}
                    </p>
                  )}
                </div>
              ) : editingRule.value_type === "percentage" ? (
                <div className="relative">
                  <input
                    type="number"
                    step="0.01"
                    min={editingRule.min_value ?? 0}
                    max={editingRule.max_value ?? 1}
                    value={editValue}
                    onChange={(e) => setEditValue(parseFloat(e.target.value) || 0)}
                    className="w-full rounded-md border border-surface-border bg-white pl-3 pr-7 py-1.5 text-sm text-slate-800 shadow-sm"
                  />
                  <span className="absolute right-3 top-2 text-sm text-slate-500">
                    {editingRule.max_value && editingRule.max_value <= 1 ? "rate (0-1)" : "%"}
                  </span>
                  {editingRule.min_value !== null && editingRule.max_value !== null && (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Allowed range: {editingRule.min_value} – {editingRule.max_value}
                    </p>
                  )}
                </div>
              ) : editingRule.value_type === "days" || editingRule.value_type === "hours" ? (
                Array.isArray(editValue) ? (
                  <div>
                    <input
                      type="text"
                      value={editValue.join(", ")}
                      onChange={(e) => {
                        const parsed = e.target.value
                          .split(",")
                          .map((s) => parseInt(s.trim()))
                          .filter((n) => !isNaN(n));
                        setEditValue(parsed);
                      }}
                      className="w-full rounded-md border border-surface-border bg-white px-3 py-1.5 text-sm text-slate-800 shadow-sm"
                    />
                    <p className="mt-1 text-[11px] text-slate-500">Comma-separated integers in descending order</p>
                  </div>
                ) : (
                  <div className="relative">
                    <input
                      type="number"
                      step="1"
                      min={editingRule.min_value ?? 0}
                      max={editingRule.max_value ?? undefined}
                      value={editValue}
                      onChange={(e) => setEditValue(parseInt(e.target.value) || 0)}
                      className="w-full rounded-md border border-surface-border bg-white pl-3 pr-14 py-1.5 text-sm text-slate-800 shadow-sm"
                    />
                    <span className="absolute right-3 top-2 text-xs text-slate-500">{editingRule.value_type}</span>
                    {editingRule.min_value !== null && editingRule.max_value !== null && (
                      <p className="mt-1 text-[11px] text-slate-500">
                        Allowed range: {editingRule.min_value} – {editingRule.max_value} {editingRule.value_type}
                      </p>
                    )}
                  </div>
                )
              ) : typeof editValue === "number" ? (
                <div className="relative">
                  <input
                    type="number"
                    step={editingRule.value_type === "float" ? "0.01" : "1"}
                    min={editingRule.min_value ?? undefined}
                    max={editingRule.max_value ?? undefined}
                    value={editValue}
                    onChange={(e) =>
                      setEditValue(
                        editingRule.value_type === "float" ? parseFloat(e.target.value) || 0 : parseInt(e.target.value) || 0,
                      )
                    }
                    className="w-full rounded-md border border-surface-border bg-white px-3 py-1.5 text-sm text-slate-800 shadow-sm"
                  />
                  {editingRule.min_value !== null && editingRule.max_value !== null && (
                    <p className="mt-1 text-[11px] text-slate-500">
                      Allowed range: {editingRule.min_value} – {editingRule.max_value}
                    </p>
                  )}
                </div>
              ) : (
                <textarea
                  rows={4}
                  value={typeof editValue === "object" ? JSON.stringify(editValue, null, 2) : String(editValue)}
                  onChange={(e) => {
                    try {
                      setEditValue(JSON.parse(e.target.value));
                    } catch {
                      setEditValue(e.target.value);
                    }
                  }}
                  className="w-full font-mono text-xs rounded-md border border-surface-border bg-white p-2 text-slate-800 shadow-sm"
                />
              )}
            </div>

            {/* Justification Textarea */}
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Audit Justification / Change Reason <span className="text-rose-500">*</span>
              </label>
              <textarea
                rows={3}
                placeholder="Explain the business rationale for modifying this rule (e.g. quarterly policy update approved by VP Finance)..."
                value={editJustification}
                onChange={(e) => setEditJustification(e.target.value)}
                className="w-full rounded-md border border-surface-border bg-white p-2.5 text-xs text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none"
              />
              <div className="flex justify-between text-[11px] text-slate-500 mt-1">
                <span>Required for audit trail and compliance.</span>
                <span className={editJustification.trim().length < 10 ? "text-rose-500 font-medium" : "text-emerald-600 font-medium"}>
                  {editJustification.trim().length}/10 chars min
                </span>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* Reset Confirmation Modal */}
      {resettingRule && (
        <Modal
          open={!!resettingRule}
          onClose={() => setResettingRule(null)}
          title={`Reset Rule: ${resettingRule.display_name}`}
          size="sm"
          footer={
            <div className="flex items-center justify-end gap-2 w-full">
              <Button variant="secondary" onClick={() => setResettingRule(null)} disabled={resetSaving}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => void handleSaveReset()}
                loading={resetSaving}
                disabled={resetJustification.trim().length < 10}
              >
                Reset to Default
              </Button>
            </div>
          }
        >
          <div className="flex flex-col gap-3 py-2">
            <p className="text-xs text-slate-600">
              Are you sure you want to reset <span className="font-semibold text-slate-900">{resettingRule.display_name}</span> to its system default value?
            </p>

            <div className="rounded-lg bg-surface-subtle border border-surface-border p-3 text-xs">
              <div className="flex justify-between mb-1">
                <span className="text-slate-500">Current Value:</span>
                <span className="font-mono text-slate-800 font-medium">{formatRuleValue(resettingRule)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Default Value:</span>
                <span className="font-mono text-emerald-700 font-semibold">
                  {typeof resettingRule.default_value === "object"
                    ? JSON.stringify(resettingRule.default_value)
                    : String(resettingRule.default_value)}
                </span>
              </div>
            </div>

            {resetError && (
              <div className="rounded-lg bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-700">
                {resetError}
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Reset Justification <span className="text-rose-500">*</span>
              </label>
              <textarea
                rows={2}
                placeholder="Reason for restoring system default value..."
                value={resetJustification}
                onChange={(e) => setResetJustification(e.target.value)}
                className="w-full rounded-md border border-surface-border bg-white p-2 text-xs text-slate-800 shadow-sm focus:border-brand-500 focus:outline-none"
              />
              <div className="text-right text-[11px] text-slate-500 mt-1">
                <span className={resetJustification.trim().length < 10 ? "text-rose-500 font-medium" : "text-emerald-600 font-medium"}>
                  {resetJustification.trim().length}/10 chars min
                </span>
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------
// Dedicated Spend Tiers Structured Editor Component
// ---------------------------------------------------------
function SpendTiersEditor({
  tiers,
  onChange,
}: {
  tiers: SpendTierItem[];
  onChange: (updated: SpendTierItem[]) => void;
}) {
  const [localTiers, setLocalTiers] = useState<SpendTierItem[]>(tiers || []);

  const updateTier = (idx: number, patch: Partial<SpendTierItem>) => {
    const next = [...localTiers];
    next[idx] = { ...next[idx], ...patch };
    setLocalTiers(next);
    onChange(next);
  };

  const toggleApprover = (idx: number, role: string) => {
    const tier = localTiers[idx];
    const exists = tier.required_approvers.includes(role);
    const updatedRoles = exists
      ? tier.required_approvers.filter((r) => r !== role)
      : [...tier.required_approvers, role];
    updateTier(idx, { required_approvers: updatedRoles });
  };

  const addTier = () => {
    const last = localTiers[localTiers.length - 1];
    const newMin = last && last.max_amount !== null ? last.max_amount : 100000;
    const newTier: SpendTierItem = {
      tier_name: `tier_${localTiers.length + 1}`,
      min_amount: newMin,
      max_amount: null,
      required_approvers: ["manager"],
      sla_hours: 48,
    };

    // If last tier had null max_amount, cap it at newMin
    const next = [...localTiers];
    if (last && last.max_amount === null) {
      next[next.length - 1] = { ...last, max_amount: newMin };
    }
    next.push(newTier);
    setLocalTiers(next);
    onChange(next);
  };

  const removeTier = (idx: number) => {
    if (localTiers.length <= 1) return;
    const next = localTiers.filter((_, i) => i !== idx);
    // adjust bounds if needed
    for (let i = 1; i < next.length; i++) {
      next[i].min_amount = next[i - 1].max_amount ?? next[i].min_amount;
    }
    setLocalTiers(next);
    onChange(next);
  };

  // Check validation rules: contiguous, no gaps, approvers non-empty
  const validationError = useMemo(() => {
    if (!localTiers || localTiers.length === 0) return "At least one spend tier must be configured.";
    for (let i = 0; i < localTiers.length; i++) {
      const t = localTiers[i];
      if (!t.tier_name.trim()) return `Tier ${i + 1} is missing a tier name.`;
      if (t.required_approvers.length === 0) return `Tier '${t.tier_name}' must have at least one approver.`;
      if (t.sla_hours <= 0) return `Tier '${t.tier_name}' SLA hours must be > 0.`;
      if (t.max_amount !== null && t.max_amount <= t.min_amount) {
        return `Tier '${t.tier_name}' Max Amount ($${t.max_amount}) must be greater than Min Amount ($${t.min_amount}).`;
      }
      if (i > 0) {
        const prev = localTiers[i - 1];
        if (prev.max_amount !== t.min_amount) {
          return `Gap/Overlap detected: '${prev.tier_name}' ends at $${prev.max_amount}, but '${t.tier_name}' starts at $${t.min_amount}. Tiers must be contiguous.`;
        }
      }
    }
    return null;
  }, [localTiers]);

  return (
    <div className="flex flex-col gap-3">
      {validationError && (
        <div className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 p-2.5 text-xs text-amber-800">
          <AlertTriangle className="size-4 shrink-0 text-amber-600" />
          <span>{validationError}</span>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-surface-border bg-white">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-surface-border bg-surface-subtle font-semibold text-slate-700">
            <tr>
              <th className="py-2 px-3">Tier Name</th>
              <th className="py-2 px-3">Min ($)</th>
              <th className="py-2 px-3">Max ($)</th>
              <th className="py-2 px-3">Required Approvers</th>
              <th className="py-2 px-3">SLA (hrs)</th>
              <th className="py-2 px-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-border">
            {localTiers.map((tier, idx) => (
              <tr key={idx} className="hover:bg-slate-50">
                <td className="py-2 px-3">
                  <input
                    type="text"
                    value={tier.tier_name}
                    onChange={(e) => updateTier(idx, { tier_name: e.target.value })}
                    className="w-24 rounded border border-surface-border px-2 py-1 text-xs"
                  />
                </td>
                <td className="py-2 px-3">
                  <input
                    type="number"
                    value={tier.min_amount}
                    onChange={(e) => updateTier(idx, { min_amount: parseFloat(e.target.value) || 0 })}
                    className="w-24 rounded border border-surface-border px-2 py-1 text-xs"
                  />
                </td>
                <td className="py-2 px-3">
                  <input
                    type="text"
                    value={tier.max_amount === null ? "Unlimited" : tier.max_amount}
                    onChange={(e) => {
                      const v = e.target.value.trim().toLowerCase();
                      if (v === "" || v === "unlimited" || v === "null") {
                        updateTier(idx, { max_amount: null });
                      } else {
                        updateTier(idx, { max_amount: parseFloat(v) || null });
                      }
                    }}
                    placeholder="Unlimited"
                    className="w-24 rounded border border-surface-border px-2 py-1 text-xs"
                  />
                </td>
                <td className="py-2 px-3">
                  <div className="flex flex-wrap gap-1.5">
                    {APPROVER_ROLES.map((role) => {
                      const checked = tier.required_approvers.includes(role);
                      return (
                        <button
                          key={role}
                          type="button"
                          onClick={() => toggleApprover(idx, role)}
                          className={`rounded px-1.5 py-0.5 text-[10px] font-medium border transition-colors ${
                            checked
                              ? "bg-brand-50 border-brand-300 text-brand-700 font-semibold"
                              : "bg-slate-50 border-slate-200 text-slate-400 hover:text-slate-600"
                          }`}
                        >
                          {role}
                        </button>
                      );
                    })}
                  </div>
                </td>
                <td className="py-2 px-3">
                  <input
                    type="number"
                    min="1"
                    value={tier.sla_hours}
                    onChange={(e) => updateTier(idx, { sla_hours: parseInt(e.target.value) || 24 })}
                    className="w-16 rounded border border-surface-border px-2 py-1 text-xs"
                  />
                </td>
                <td className="py-2 px-3 text-right">
                  <button
                    type="button"
                    disabled={localTiers.length <= 1}
                    onClick={() => removeTier(idx)}
                    className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-30"
                    title="Remove tier"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex justify-between items-center text-xs">
        <span className="text-slate-500">Tiers must be contiguous without gaps. Empty max amount represents unlimited.</span>
        <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={addTier}>
          Add Tier
        </Button>
      </div>
    </div>
  );
}
