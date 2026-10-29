import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ContractStatusBadge, RiskBadge } from "@/components/ui/Badge";
import { ErrorState, InlineError } from "@/components/ui/ErrorState";
import { FilterChip } from "@/components/ui/FilterChip";
import { ApiError } from "@/api/client";
import { GenerateContractModal } from "@/components/contracts/GenerateContractModal";
import { Button } from "@/components/ui/Button";
import { Download, Plus } from "lucide-react";
import { formatDate, titleCase } from "@/lib/format";
import type { Contract } from "@/types/api";

export function ContractsListPage() {
  usePageHeader("Contracts");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: contracts, loading, error, reload } = useApi(() => contractsApi.list(200), []);
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  // ?status=signed, ?renewal=60 (renewal deadline within 60 days), ?vendor=<id>
  const [params, setParams] = useSearchParams();
  const statusFilter = params.get("status");
  const renewalDays = Number(params.get("renewal")) || null;
  const vendorFilter = params.get("vendor");
  const { data: renewals } = useApi(
    () => (renewalDays ? contractsApi.renewalsDue(renewalDays) : Promise.resolve({ data: [] as Contract[] })),
    [renewalDays],
  );
  const [generateOpen, setGenerateOpen] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const vendorName = (id: string | null) => vendors?.find((v) => v.id === id)?.name ?? (id ? "Unknown vendor" : "—");
  const vendorRisk = useMemo(() => new Map(vendors?.map((v) => [v.id, v]) ?? []), [vendors]);

  const renewalIds = useMemo(() => new Set((renewals ?? []).map((c) => c.id)), [renewals]);
  const rows = (contracts ?? []).filter(
    (c) =>
      (!statusFilter || c.status === statusFilter) &&
      (!renewalDays || renewalIds.has(c.id)) &&
      (!vendorFilter || c.vendor_id === vendorFilter),
  );
  const filterLabel = [
    statusFilter && titleCase(statusFilter),
    renewalDays && `renewing within ${renewalDays} days`,
    vendorFilter && vendorName(vendorFilter),
  ]
    .filter(Boolean)
    .join(" · ");

  const columns: Column<Contract>[] = [
    { key: "id", header: "Contract", render: (c) => <span className="font-mono text-xs">{c.id.slice(0, 8)}</span> },
    { key: "vendor", header: "Vendor", render: (c) => vendorName(c.vendor_id) },
    { key: "type", header: "Type", render: (c) => <span className="capitalize">{titleCase(c.template_used)}</span> },
    { key: "end", header: "End Date", render: (c) => formatDate(c.contract_end_date), sortValue: (c) => c.contract_end_date ?? "" },
    { key: "renewal", header: "Renewal", render: (c) => <span className="capitalize">{c.renewal_type ?? "—"}</span> },
    { key: "status", header: "Status", render: (c) => <ContractStatusBadge status={c.status} /> },
    { key: "risk", header: "Vendor Risk", render: (c) => <RiskBadge band={vendorRisk.get(c.vendor_id ?? "")?.risk_band ?? null} ratingStatus={vendorRisk.get(c.vendor_id ?? "")?.rating_status} /> },
    {
      key: "download",
      header: "",
      className: "w-px text-right",
      render: (c) => (
        <button
          onClick={(e) => {
            e.stopPropagation();
            const run = c.status === "signed" ? contractsApi.downloadSigned : contractsApi.downloadDocument;
            run(c.id).catch((err) => setDownloadError(err instanceof ApiError ? err.message : "Download failed."));
          }}
          className="inline-flex items-center gap-1 whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-medium text-brand-700 hover:bg-brand-50"
          title={c.status === "signed" ? "Download the signed copy" : "Download the contract PDF"}
        >
          <Download className="size-3.5" />
          {c.status === "signed" ? "Signed PDF" : "PDF"}
        </button>
      ),
    },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {filterLabel ? <FilterChip label={filterLabel} onClear={() => setParams({}, { replace: true })} /> : <span />}
        {(user?.role === "approver" || user?.role === "finance" || user?.role === "admin") && (
          <Button icon={<Plus className="size-4" />} onClick={() => setGenerateOpen(true)}>
            Generate contract
          </Button>
        )}
      </div>
      {downloadError && <InlineError message={downloadError} />}
      <Card>
        <CardBody className="p-2 sm:p-0">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(c) => c.id}
            loading={loading}
            onRowClick={(c) => navigate(`/app/contracts/${c.id}`)}
            emptyTitle={filterLabel ? "No contracts match this filter" : "No contracts yet"}
          />
        </CardBody>
      </Card>
      <GenerateContractModal open={generateOpen} onClose={() => setGenerateOpen(false)} onGenerated={(id) => navigate(`/app/contracts/${id}`)} />
    </div>
  );
}
