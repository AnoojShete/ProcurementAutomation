import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "@/api/client";
import { catalogApi } from "@/api/catalog";
import { requestsApi } from "@/api/requests";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { formatCurrency } from "@/lib/format";
import type { CatalogCategory, CatalogItem, LicenseItem, VendorSummary } from "@/types/api";

/** Every catalog action (Phase 3a): order items as a purchase request
 * (anyone), and add, reprice or switch off items (finance, admin). Calls
 * only the approval agent's API. */

const field = "h-9 w-full rounded border border-rule-strong bg-sheet px-2.5 text-sm text-ink focus:border-accent";
const label = "flex flex-col gap-1 text-13 text-ink-2";

function message(e: unknown, fallback: string) {
  return e instanceof ApiError ? e.message : fallback;
}

export type Basket = Record<string, number>;

/** The basket: quantities per catalog item, then one request. */
export function OrderFromCatalog({ items, basket, setBasket, defaultDepartment }: {
  items: CatalogItem[]; basket: Basket; setBasket: (b: Basket) => void; defaultDepartment?: string;
}) {
  const navigate = useNavigate();
  const [department, setDepartment] = useState(defaultDepartment ?? "");
  const [comments, setComments] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chosen = items.filter((i) => basket[i.id] > 0);
  const total = chosen.reduce((t, i) => t + i.unit_price * basket[i.id], 0);
  const vendors = new Set(chosen.map((i) => i.vendor_id));
  const types = new Set(chosen.map((i) => i.request_type));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!department.trim()) return setError("Enter the department the request is for.");
    setBusy(true);
    try {
      const res = await requestsApi.create({
        request_type: chosen[0].request_type, requested_by: "", department: department.trim(), amount: total,
        currency: "INR", vendor_id: chosen[0].vendor_id ?? undefined, comments: comments.trim() || undefined,
        items: chosen.map((i) => ({ catalog_item_id: i.id, quantity: basket[i.id] })),
      });
      setBasket({});
      navigate(`/app/requests/${res.data.id}`);
    } catch (err) {
      setError(message(err, "Unable to create the request."));
    } finally {
      setBusy(false);
    }
  };

  if (!chosen.length) {
    return <p className="text-13 text-ink-3">Add items from the list to order them. Prices are agreed, so the budget check and approval route are exact.</p>;
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <ul className="flex flex-col">
        {chosen.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-rule py-2 text-13 last:border-0">
            <span className="text-ink">{i.name} <span className="text-ink-3">· {formatCurrency(i.unit_price)} each</span></span>
            <span className="flex items-center gap-2">
              <input aria-label={`Quantity of ${i.name}`} className={`${field} w-20`} type="number" min={1} value={basket[i.id]}
                onChange={(e) => setBasket({ ...basket, [i.id]: Math.max(0, Math.floor(Number(e.target.value) || 0)) })} />
              <Button size="sm" variant="ghost" onClick={() => setBasket({ ...basket, [i.id]: 0 })}>Remove</Button>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-sm text-ink">Total <span className="font-medium tabular">{formatCurrency(total)}</span></p>
      {vendors.size > 1 && <p role="alert" className="text-13 text-danger-600">These items come from different vendors: order them as separate requests.</p>}
      {types.size > 1 && <p role="alert" className="text-13 text-danger-600">Hardware and software go in separate requests.</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className={label}>Department
          <input className={field} value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Engineering" />
        </label>
        <label className={label}>Comments (optional)
          <input className={field} value={comments} onChange={(e) => setComments(e.target.value)} placeholder="New joiners in November" />
        </label>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" loading={busy} disabled={vendors.size > 1 || types.size > 1}>Create request</Button>
        {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
      </div>
    </form>
  );
}

const EMPTY = { sku: "", name: "", category: "hardware" as CatalogCategory, vendor_id: "", unit_price: "", lead_time_days: "",
                warranty_months: "", valid_until: "", license_id: "", inventory_sku: "", spec: "" };

/** Finance / admin: add an item. Spec is "key: value" per line. */
export function AddCatalogItem({ vendors, licenses, onChanged }: {
  vendors: VendorSummary[]; licenses: LicenseItem[]; onChanged: () => void;
}) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const set = (k: keyof typeof EMPTY) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value });
  const num = (v: string) => (v.trim() === "" ? null : Number(v));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setDone(null);
    const price = Number(form.unit_price);
    if (!form.sku.trim() || !form.name.trim() || !form.vendor_id || !Number.isFinite(price) || price < 0) {
      return setError("SKU, name, vendor and a price of zero or more are needed.");
    }
    const spec = Object.fromEntries(form.spec.split("\n").map((l) => l.split(":")).filter((p) => p.length >= 2 && p[0].trim())
      .map(([k, ...v]) => [k.trim(), v.join(":").trim()]));
    setBusy(true);
    try {
      const res = await catalogApi.create({
        sku: form.sku.trim(), name: form.name.trim(), category: form.category, vendor_id: form.vendor_id, unit_price: price,
        lead_time_days: num(form.lead_time_days), warranty_months: num(form.warranty_months), valid_until: form.valid_until || null,
        license_id: form.category !== "hardware" ? form.license_id || null : null,
        inventory_sku: form.category === "hardware" ? form.inventory_sku.trim() || null : null, spec,
      });
      setDone(`${res.data.name} added at ${formatCurrency(res.data.unit_price)}.`);
      setForm(EMPTY);
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to add the item."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="Add a catalog item" subtitle="An agreed price from a contract or negotiation. Seat add-ons add seats to a licence when received." />
      <CardBody>
        <form onSubmit={submit} className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
          <label className={label}>SKU<input className={field} value={form.sku} onChange={set("sku")} placeholder="LAP-DEV-32" /></label>
          <label className={`${label} lg:col-span-2`}>Name<input className={field} value={form.name} onChange={set("name")} placeholder="Developer laptop, 32 GB, 3-year warranty" /></label>
          <label className={label}>Category
            <select className={field} value={form.category} onChange={set("category")}>
              <option value="hardware">Hardware</option><option value="software">Software licence</option><option value="saas">SaaS</option>
            </select>
          </label>
          <label className={label}>Vendor
            <select className={field} value={form.vendor_id} onChange={set("vendor_id")}>
              <option value="">Choose a vendor</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </label>
          <label className={label}>Unit price (₹)<input className={field} inputMode="decimal" value={form.unit_price} onChange={set("unit_price")} /></label>
          <label className={label}>Lead time (days)<input className={field} inputMode="numeric" value={form.lead_time_days} onChange={set("lead_time_days")} /></label>
          <label className={label}>Warranty (months)<input className={field} inputMode="numeric" value={form.warranty_months} onChange={set("warranty_months")} /></label>
          {form.category === "hardware" ? (
            <label className={label}>Stock SKU (optional)<input className={field} value={form.inventory_sku} onChange={set("inventory_sku")} placeholder="Reserved from stock first" /></label>
          ) : (
            <label className={label}>Adds seats to (optional)
              <select className={field} value={form.license_id} onChange={set("license_id")}>
                <option value="">A new subscription</option>
                {licenses.map((l) => <option key={l.id} value={l.id}>{l.app_name} ({l.total_seats} seats)</option>)}
              </select>
            </label>
          )}
          <label className={label}>Price valid until (optional)<input className={field} type="date" value={form.valid_until} onChange={set("valid_until")} /></label>
          <label className={`${label} sm:col-span-2`}>Spec (optional, one "key: value" per line)
            <textarea className={`${field} h-16 py-2`} value={form.spec} onChange={set("spec")} placeholder={"RAM: 32 GB\nWarranty: on-site"} />
          </label>
          <div className="flex items-center gap-3 sm:col-span-2 lg:col-span-4">
            <Button type="submit" loading={busy}>Add item</Button>
            {error && <p role="alert" className="text-13 text-danger-600">{error}</p>}
            {done && <p role="status" className="text-13 text-success-700">{done}</p>}
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

/** Finance / admin, per row: change the price or switch the item off/on. */
export function CatalogItemControls({ item, onChanged }: { item: CatalogItem; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const act = async (body: Parameters<typeof catalogApi.update>[1]) => {
    setBusy(true);
    setError(null);
    try {
      await catalogApi.update(item.id, body);
      onChanged();
    } catch (err) {
      setError(message(err, "Unable to change the item."));
    } finally {
      setBusy(false);
    }
  };
  const reprice = () => {
    const typed = window.prompt(`New agreed price for ${item.name} (₹)`, String(item.unit_price));
    if (typed === null) return;
    const price = Number(typed);
    if (!Number.isFinite(price) || price < 0) return setError("Enter a price of zero or more.");
    act({ unit_price: price });
  };
  return (
    <span className="flex flex-wrap items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <Button size="sm" variant="ghost" loading={busy} onClick={reprice}>Change price</Button>
      <Button size="sm" variant="ghost" loading={busy} onClick={() => act({ active: !item.active })}>{item.active ? "Switch off" : "Switch on"}</Button>
      {error && <span role="alert" className="text-13 text-danger-600">{error}</span>}
    </span>
  );
}
