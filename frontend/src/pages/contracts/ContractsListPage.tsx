import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { contractsApi } from "@/api/contracts";
import { vendorsApi } from "@/api/vendors";
import { Card, CardBody } from "@/components/ui/Card";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ContractStatusBadge, RiskBadge } from "@/components/ui/Badge";
import { ErrorState } from "@/components/ui/ErrorState";
import { GenerateContractModal } from "@/components/contracts/GenerateContractModal";
import { Button } from "@/components/ui/Button";
import { Plus } from "lucide-react";
import { formatDate, titleCase } from "@/lib/format";
import type { Contract } from "@/types/api";

export function ContractsListPage() {
  usePageHeader("Contracts");
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: contracts, loading, error, reload } = useApi(() => contractsApi.list(200), []);
  const { data: vendors } = useApi(() => vendorsApi.list(200), []);
  const [generateOpen, setGenerateOpen] = useState(false);

  const vendorName = (id: string | null) => vendors?.find((v) => v.id === id)?.name ?? (id ? "Unknown vendor" : "—");
  const vendorRisk = useMemo(() => new Map(vendors?.map((v) => [v.id, v.risk_band]) ?? []), [vendors]);

  const columns: Column<Contract>[] = [
    { key: "id", header: "Contract", render: (c) => <span className="font-mono text-xs">{c.id.slice(0, 8)}</span> },
    { key: "vendor", header: "Vendor", render: (c) => vendorName(c.vendor_id) },
    { key: "type", header: "Type", render: (c) => <span className="capitalize">{titleCase(c.template_used)}</span> },
    { key: "end", header: "End Date", render: (c) => formatDate(c.contract_end_date), sortValue: (c) => c.contract_end_date ?? "" },
    { key: "renewal", header: "Renewal", render: (c) => <span className="capitalize">{c.renewal_type ?? "—"}</span> },
    { key: "status", header: "Status", render: (c) => <ContractStatusBadge status={c.status} /> },
    { key: "risk", header: "Vendor Risk", render: (c) => <RiskBadge band={vendorRisk.get(c.vendor_id ?? "") ?? null} /> },
  ];

  if (error) return <ErrorState message={error} onRetry={reload} />;

  return (
    <div className="flex flex-col gap-4">
      {(user?.role === "approver" || user?.role === "finance" || user?.role === "admin") && (
        <div className="flex justify-end">
          <Button icon={<Plus className="size-4" />} onClick={() => setGenerateOpen(true)}>
            Generate Contract
          </Button>
        </div>
      )}
      <Card>
        <CardBody>
          <DataTable
            columns={columns}
            rows={contracts ?? []}
            rowKey={(c) => c.id}
            loading={loading}
            onRowClick={(c) => navigate(`/app/contracts/${c.id}`)}
            emptyTitle="No contracts require attention"
            emptyDescription="Contracts generated from approved purchase requests will appear here."
          />
        </CardBody>
      </Card>
      <GenerateContractModal open={generateOpen} onClose={() => setGenerateOpen(false)} onGenerated={(id) => navigate(`/app/contracts/${id}`)} />
    </div>
  );
}
