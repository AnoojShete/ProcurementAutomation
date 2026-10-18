import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { Badge, RiskBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { FilterChip } from "@/components/ui/FilterChip";
import { Button } from "@/components/ui/Button";
import { VendorOnboardingForm } from "@/components/vendors/VendorOnboardingForm";
import { useAuth } from "@/hooks/useAuth";
import { formatDate } from "@/lib/format";
import { UserPlus } from "lucide-react";
import type { VendorSummary } from "@/types/api";

export function VendorsListPage() {
  usePageHeader("Vendors");
  const navigate = useNavigate();
  const { data: vendors, loading, error, reload } = useApi(() => vendorsApi.list(200), []);
  const [query, setQuery] = useState("");
  const [onboarding, setOnboarding] = useState(false);
  const { user } = useAuth();
  const canOnboard = ["finance", "admin"].includes(user?.role ?? "");

  // ?status=active and ?risk=High come from dashboard figures.
  const [params, setParams] = useSearchParams();
  const statusFilter = params.get("status");
  const riskFilter = params.get("risk");
  const filterLabel = [statusFilter, riskFilter && `${riskFilter} risk`].filter(Boolean).join(" · ");

  const rows = (vendors ?? []).filter(
    (v) =>
      v.name.toLowerCase().includes(query.toLowerCase()) &&
      (!statusFilter || v.status === statusFilter) &&
      (!riskFilter || v.risk_band === riskFilter),
  );

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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search vendors…"
          aria-label="Search vendors"
          className="field max-w-sm"
        />
        {filterLabel && (
          <span className="mr-auto">
            <FilterChip label={filterLabel} onClear={() => setParams({}, { replace: true })} />
          </span>
        )}
        {canOnboard && (
          <Button icon={<UserPlus className="size-3.5" />} onClick={() => setOnboarding(true)}>
            Onboard vendor
          </Button>
        )}
      </div>
      <VendorOnboardingForm
        open={onboarding}
        onClose={() => setOnboarding(false)}
        onOnboarded={(id) => navigate(`/app/vendors/${id}`)}
      />
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(v) => v.id}
            loading={loading}
            onRowClick={(v) => navigate(`/app/vendors/${v.id}`)}
            emptyTitle={filterLabel || query ? "No vendors match" : "No vendors yet"}
          />
        </CardBody>
      </Card>
    </div>
  );
}
