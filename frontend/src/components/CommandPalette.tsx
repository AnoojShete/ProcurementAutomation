import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Building2, FileText, ScrollText, Search, Files } from "lucide-react";
import { requestsApi } from "@/api/requests";
import { vendorsApi } from "@/api/vendors";
import { contractsApi } from "@/api/contracts";
import { documentsApi } from "@/api/documents";
import { documentTypeLabel, formatCurrency } from "@/lib/format";

interface SearchResult {
  group: "Requests" | "Vendors" | "Contracts" | "Documents";
  id: string;
  title: string;
  subtitle: string;
  to: string;
}

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) {
      setQuery("");
      setResults(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    Promise.all([
      requestsApi.list(200).catch(() => ({ data: [] })),
      vendorsApi.list(200).catch(() => ({ data: [] })),
      contractsApi.list(200).catch(() => ({ data: [] })),
      documentsApi.list(200).catch(() => ({ data: [] })),
    ]).then(([reqs, vendors, contracts, docs]) => {
      if (cancelled) return;
      const all: SearchResult[] = [
        ...reqs.data.map((r) => ({
          group: "Requests" as const,
          id: r.id,
          title: `${r.request_type ?? "Request"} — ${r.department ?? "—"}`,
          subtitle: `${formatCurrency(r.amount, r.currency ?? "INR")} · ${r.status ?? "unknown"} · ${r.id.slice(0, 8)}`,
          to: `/app/requests/${r.id}`,
        })),
        ...vendors.data.map((v) => ({
          group: "Vendors" as const,
          id: v.id,
          title: v.name,
          subtitle: `${v.risk_band ?? "Not scored"} · ${v.id.slice(0, 8)}`,
          to: `/app/vendors/${v.id}`,
        })),
        ...contracts.data.map((c) => ({
          group: "Contracts" as const,
          id: c.id,
          title: `Contract ${c.id.slice(0, 8)}`,
          subtitle: `${c.template_used ?? "—"} · ${c.status} `,
          to: `/app/contracts/${c.id}`,
        })),
        ...docs.data.map((d) => ({
          group: "Documents" as const,
          id: d.id,
          title: d.original_filename ?? `Document ${d.id.slice(0, 8)}`,
          subtitle: `${documentTypeLabel(d.document_type)} · ${d.status}`,
          to: `/app/documents/${d.id}`,
        })),
      ];
      setResults(all);
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

  const filtered = useMemo(() => {
    if (!results) return null;
    const needle = query.trim().toLowerCase();
    if (!needle) return results.slice(0, 20);
    return results.filter((r) => `${r.title} ${r.subtitle}`.toLowerCase().includes(needle)).slice(0, 40);
  }, [results, query]);

  const grouped = useMemo(() => {
    const map = new Map<string, SearchResult[]>();
    (filtered ?? []).forEach((r) => {
      if (!map.has(r.group)) map.set(r.group, []);
      map.get(r.group)!.push(r);
    });
    return map;
  }, [filtered]);

  const groupIcon: Record<SearchResult["group"], typeof Search> = {
    Requests: FileText,
    Vendors: Building2,
    Contracts: ScrollText,
    Documents: Files,
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
      }
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-24" role="presentation">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} aria-hidden="true" />
      <div className="relative z-10 w-full max-w-xl overflow-hidden rounded-xl bg-white shadow-popover animate-slide-up">
        <div className="flex items-center gap-2 border-b border-surface-border px-4 py-3">
          <Search className="size-4 text-slate-400" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search requests, vendors, contracts, documents…"
            aria-label="Global search"
            className="flex-1 border-none text-sm outline-none placeholder:text-slate-400"
          />
          <kbd className="rounded border border-surface-border bg-surface-subtle px-1.5 py-0.5 text-[11px] text-slate-400">Esc</kbd>
        </div>
        <div className="max-h-96 overflow-y-auto p-2">
          {filtered === null && <p className="px-2 py-6 text-center text-sm text-slate-400">Loading…</p>}
          {filtered !== null && filtered.length === 0 && (
            <p className="px-2 py-6 text-center text-sm text-slate-400">No matches for "{query}".</p>
          )}
          {Array.from(grouped.entries()).map(([group, items]) => {
            const Icon = groupIcon[group as SearchResult["group"]];
            return (
              <div key={group} className="mb-2 last:mb-0">
                <p className="px-2 py-1 text-xs font-medium uppercase tracking-wide text-slate-400">{group}</p>
                {items.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => {
                      navigate(item.to);
                      onClose();
                    }}
                    className="flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left hover:bg-surface-subtle"
                  >
                    <Icon className="size-4 shrink-0 text-slate-400" />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-slate-800">{item.title}</p>
                      <p className="truncate text-xs text-slate-500">{item.subtitle}</p>
                    </div>
                  </button>
                ))}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
