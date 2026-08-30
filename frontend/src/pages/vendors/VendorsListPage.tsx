import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge, RiskBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { formatDate } from "@/lib/format";
import type { VendorSummary } from "@/types/api";

export function VendorsListPage() {
  usePageHeader("Vendors");
  const navigate = useNavigate();
  const { data: vendors, loading, error, reload } = useApi(() => vendorsApi.list(200), []);
  const [query, setQuery] = useState("");

  const rows = (vendors ?? []).filter((v) => v.name.toLowerCase().includes(query.toLowerCase()));

  const columns: Column<VendorSummary>[] = [
    { key: "name", header: "Vendor", render: (v) => <span className="font-medium text-slate-800">{v.name}</span> },
    { key: "status", header: "Status", render: (v) => <Badge tone={v.status === "active" ? "success" : "neutral"}>{v.status}</Badge> },
    { key: "risk", header: "Risk", render: (v) => <RiskBadge band={v.risk_band} /> },
    { key: "score", header: "Score", render: (v) => (v.risk_score != null ? v.risk_score.toFixed(2) : "—"), sortValue: (v) => v.risk_score ?? -1 },
    { key: "portal", header: "Portal Access", render: (v) => (v.portal_access_revoked ? <Badge tone="danger">Revoked</Badge> : <Badge tone="success">Active</Badge>) },
    { key: "created", header: "Onboarded", render: (v) => formatDate(v.created_at), sortValue: (v) => v.created_at ?? "" },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search vendors…"
        className="w-full max-w-sm rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
      />
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(v) => v.id}
            loading={loading}
            onRowClick={(v) => navigate(`/app/vendors/${v.id}`)}
            emptyTitle="No vendors yet"
            emptyDescription="Vendors are onboarded automatically when documents are matched to them."
          />
        </CardBody>
      </Card>
    </div>
  );
}
