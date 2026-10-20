import { useParams, Link } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { vendorsApi } from "@/api/vendors";
import { VendorRiskScorecard } from "@/components/vendors/VendorRiskScorecard";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";

export function VendorRiskScorecardPage() {
  const { id } = useParams<{ id: string }>();
  const { data: vendors, loading, error, reload } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === id) ?? null;

  usePageHeader(vendor ? `${vendor.name} — Risk Scorecard` : "Vendor Risk Scorecard", "Vendors");

  if (loading && !vendors) return <Skeleton className="h-96" />;
  if (error || (!loading && !vendor)) {
    return <ErrorState message={error ?? "Vendor not found."} onRetry={reload} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <VendorRiskScorecard
        vendorId={id!}
        vendorName={vendor?.name}
        vendorTier="Tier 1"
      />
    </div>
  );
}
