import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { ShoppingCart, CheckCircle2, AlertTriangle, ShieldCheck, ShieldAlert, ArrowRight, ExternalLink } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { InlineError } from "@/components/ui/ErrorState";
import { useAuth } from "@/hooks/useAuth";
import { useApi } from "@/hooks/useApi";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { budgetsApi } from "@/api/budgets";
import { formatCurrency } from "@/lib/format";
import type { InventoryItem } from "@/types/api";

interface PlaceReorderModalProps {
  item: InventoryItem | null;
  open: boolean;
  onClose: () => void;
  onSuccess: (requestId: string) => void;
}

export function PlaceReorderModal({ item, open, onClose, onSuccess }: PlaceReorderModalProps) {
  const { user } = useAuth();
  const initialQty = item?.reorder?.suggested_quantity ?? 1;
  const initialCost = item?.unit_cost && item.unit_cost > 0 ? item.unit_cost : "";

  const [quantity, setQuantity] = useState<number>(initialQty);
  const [department, setDepartment] = useState<string>("IT");
  const [unitCost, setUnitCost] = useState<number | "">(initialCost);
  const [placeAdditional, setPlaceAdditional] = useState(false);
  const [comments, setComments] = useState<string>(
    item ? `Stock replenishment for ${item.name} (${item.sku}): ${item.reorder?.explanation ?? "low stock"}` : "",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Prompt 10 Section 4.3: Duplicate guard (check open requests for this SKU)
  const { data: allRequests } = useApi(() => requestsApi.list(), []);
  const openRequestForSku = useMemo(() => {
    if (!allRequests || !item) return null;
    return allRequests.find((r) => {
      const isOpen = Boolean(r.status && ["pending_approval", "approved", "ordered"].includes(r.status as any));
      const hasSku =
        (r.items || []).some((it: any) => it.sku === item.sku) ||
        (r.comments && r.comments.includes(item.sku));
      return isOpen && hasSku;
    });
  }, [allRequests, item]);

  // Prompt 10 Section 4.2: Live Vendor Clearance
  const { data: clearance } = useApi(
    () => (item?.vendor_id ? vendorsApi.clearance(item.vendor_id as string, "purchase") : Promise.resolve({ data: null })),
    [item?.vendor_id],
  );

  // Prompt 10 Section 4.2: Live Budget Check
  const { data: budgets } = useApi(() => budgetsApi.list(), []);
  const departmentBudget = useMemo(() => {
    if (!budgets || !department) return null;
    return budgets.find((b) => b.department.toLowerCase() === department.trim().toLowerCase());
  }, [budgets, department]);

  const totalAmount = useMemo(() => {
    const cost = typeof unitCost === "number" ? unitCost : 0;
    return Math.max(1, quantity) * Math.max(0, cost);
  }, [quantity, unitCost]);

  const isOverBudget = useMemo(() => {
    if (!departmentBudget) return false;
    const remaining = (departmentBudget as any).remaining_inr ?? 0;
    return totalAmount > remaining;
  }, [departmentBudget, totalAmount]);

  if (!item) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (quantity <= 0) {
      setError("Please enter a valid quantity of at least 1 unit.");
      return;
    }
    if (typeof unitCost !== "number" || unitCost <= 0) {
      setError("Please enter a valid unit price. Invented zero prices are not permitted.");
      return;
    }
    if (!department.trim()) {
      setError("Please specify the department requesting this reorder.");
      return;
    }
    if (openRequestForSku && !placeAdditional) {
      setError("An open request already exists for this SKU. Check 'Place additional order' to proceed.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      const res = await requestsApi.create({
        request_type: "hardware",
        requested_by: user?.email ?? "",
        department: department.trim(),
        amount: totalAmount,
        currency: item.currency ?? "INR",
        vendor_id: item.vendor_id || undefined,
        comments: comments.trim() || undefined,
        source: "reorder_suggestion",
        source_ref: item.id,
        idempotency_key: crypto.randomUUID(),
        items: [
          {
            sku: item.sku,
            name: item.name,
            quantity: Number(quantity),
            unit_price: Number(unitCost),
          },
        ],
      });

      onSuccess(res.data.id);
    } catch (err: any) {
      setError(err?.message || "Unable to place purchase request for reorder.");
    } finally {
      setSubmitting(false);
    }
  };

  const isSubmitDisabled =
    submitting ||
    Boolean(openRequestForSku && !placeAdditional) ||
    typeof unitCost !== "number" ||
    unitCost <= 0;

  return (
    <Modal
      open={open}
      onClose={() => !submitting && onClose()}
      title="Place Reorder Request"
      size="md"
      footer={
        <div className="flex w-full items-center justify-between">
          <span className="text-xs text-ink-3">
            Estimated Total: <strong className="text-ink">{formatCurrency(totalAmount, item.currency ?? "INR")}</strong>
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" disabled={submitting} onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" loading={submitting} disabled={isSubmitDisabled} onClick={handleSubmit}>
              <ShoppingCart className="mr-1.5 size-4" />
              Submit Request
            </Button>
          </div>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="flex flex-col gap-4 text-sm">
        {/* Item Details Header */}
        <div className="rounded-lg border border-rule bg-sheet-sunk p-3 text-xs">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-ink text-sm">{item.name}</span>
            <span className="font-mono text-ink-3">{item.sku}</span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 border-t border-rule/60 pt-2 text-ink-2">
            <div>
              <span className="text-ink-3 block">Available Stock:</span>
              <span className="font-medium">{item.available_quantity} units</span>
            </div>
            <div>
              <span className="text-ink-3 block">Reorder Point:</span>
              <span className="font-medium">{item.reorder?.reorder_point ?? "—"} units</span>
            </div>
            <div>
              <span className="text-ink-3 block">Suggested Order:</span>
              <span className="font-medium text-amber-800">{item.reorder?.suggested_quantity ?? 0} units</span>
            </div>
          </div>
          {item.reorder?.explanation && (
            <p className="mt-2 text-ink-3 italic">{item.reorder.explanation}</p>
          )}
        </div>

        {/* Prompt 10 Section 4.3: Duplicate Guard Banner */}
        {openRequestForSku && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 font-medium">
                <AlertTriangle className="size-4 shrink-0 text-amber-600" />
                <span>
                  Request already open for this SKU: <strong>PR-{openRequestForSku.id.slice(0, 8)}</strong> ({openRequestForSku.status})
                </span>
              </div>
              <Link to={`/app/requests/${openRequestForSku.id}`} target="_blank" className="font-semibold text-accent hover:underline flex items-center gap-0.5">
                View <ExternalLink className="size-3" />
              </Link>
            </div>
            <label className="flex items-center gap-2 cursor-pointer font-medium pt-1 text-ink">
              <input
                type="checkbox"
                checked={placeAdditional}
                onChange={(e) => setPlaceAdditional(e.target.checked)}
                className="size-4 rounded border-rule-strong text-accent focus:ring-accent"
              />
              <span>Place additional order despite existing open request</span>
            </label>
          </div>
        )}

        {/* Vendor Clearance & Budget Status */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded border border-rule bg-sheet-sunk p-2 flex items-center justify-between">
            <span className="text-ink-3">Vendor Clearance:</span>
            {item.vendor_id ? (
              clearance?.cleared ? (
                <Badge tone="success">
                  <ShieldCheck className="mr-1 size-3" />
                  Cleared
                </Badge>
              ) : (
                <Badge tone="danger">
                  <ShieldAlert className="mr-1 size-3" />
                  Not Cleared
                </Badge>
              )
            ) : (
              <span className="text-ink-3">No Vendor Assigned</span>
            )}
          </div>
          <div className="rounded border border-rule bg-sheet-sunk p-2 flex items-center justify-between">
            <span className="text-ink-3">Dept Budget:</span>
            {departmentBudget ? (
              <span className={isOverBudget ? "text-danger font-medium" : "text-ink font-medium"}>
                {formatCurrency((departmentBudget as any).remaining_inr ?? 0)} left
              </span>
            ) : (
              <span className="text-ink-3">No Budget Found</span>
            )}
          </div>
        </div>

        {isOverBudget && (
          <div className="rounded border border-danger/30 bg-danger/10 p-2 text-xs text-danger flex items-center gap-1.5">
            <AlertTriangle className="size-4 shrink-0" />
            <span>Warning: Reorder total exceeds department remaining budget. Over-budget approval step will be required.</span>
          </div>
        )}

        {error && <InlineError message={error} />}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-2">Quantity to Order *</label>
            <input
              type="number"
              min={1}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
              required
              className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-ink-2">
              Unit Price ({item.currency ?? "INR"}) *
            </label>
            <input
              type="number"
              min={0.01}
              step="any"
              value={unitCost}
              placeholder="Enter price from quotation"
              onChange={(e) => {
                const val = e.target.value;
                setUnitCost(val === "" ? "" : Math.max(0, parseFloat(val) || 0));
              }}
              required
              className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
            />
            {item.unit_cost == null && (
              <span className="mt-1 block text-[11px] text-ink-3">No purchase history on record. Unit price must be entered.</span>
            )}
          </div>
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-ink-2">Requesting Department *</label>
          <input
            type="text"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            required
            className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
            placeholder="e.g. IT, Engineering, Operations"
          />
        </div>

        <div>
          <label className="mb-1 block text-xs font-medium text-ink-2">Reorder Justification / Comments</label>
          <textarea
            rows={2}
            value={comments}
            onChange={(e) => setComments(e.target.value)}
            className="w-full rounded border border-rule-strong bg-sheet p-2 text-sm text-ink focus:border-accent focus:outline-none"
            placeholder="Comments for approvers..."
          />
        </div>
      </form>
    </Modal>
  );
}
