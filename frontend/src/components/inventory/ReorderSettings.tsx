import { useState } from "react";
import { inventoryApi } from "@/api/inventory";
import { ApiError } from "@/api/client";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import type { InventoryItem } from "@/types/api";

/**
 * Edit an item's reorder point and reorder quantity (BR-5). Leaving a box
 * empty goes back to the business-rule default. Talks only to
 * approval-inventory-agent (/inventory).
 */
export function ReorderSettings({
  item,
  onClose,
  onSaved,
}: {
  item: InventoryItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const r = item.reorder;
  const [point, setPoint] = useState(r?.point_source === "item" ? String(r.reorder_point) : "");
  const [quantity, setQuantity] = useState(r?.quantity_source === "item" ? String(r.reorder_quantity) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await inventoryApi.setReorderSettings(item.id, point === "" ? null : Number(point), quantity === "" ? null : Number(quantity));
      onSaved();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Saving failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={`Reorder settings — ${item.name}`}
      size="sm"
      footer={
        <div className="flex justify-end">
          <Button loading={busy} onClick={save}>Save</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3">
        <label>
          <span className="mb-1 block text-xs font-medium text-slate-600">Reorder point (units)</span>
          <input className="field" type="number" min={0} value={point} onChange={(e) => setPoint(e.target.value)}
            placeholder={r?.point_source === "rule" ? `Default: ${r.reorder_point}` : "Default from business rules"} />
        </label>
        <label>
          <span className="mb-1 block text-xs font-medium text-slate-600">Reorder quantity (units)</span>
          <input className="field" type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)}
            placeholder={r?.quantity_source === "rule" ? `Default: ${r.reorder_quantity}` : "Default from business rules"} />
        </label>
        <p className="text-xs text-slate-500">
          Leave empty to use the defaults in Business Rules (a share of the item's total stock).
        </p>
        {error && <p className="text-sm text-danger-600">{error}</p>}
      </div>
    </Modal>
  );
}
