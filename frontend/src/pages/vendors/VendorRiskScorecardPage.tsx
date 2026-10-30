import React, { Component, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { vendorsApi } from "@/api/vendors";
import { VendorRiskScorecard } from "@/components/vendors/VendorRiskScorecard";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";

interface ErrorBoundaryProps {
  children: ReactNode;
  onRetry?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class ScorecardErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error("ScorecardErrorBoundary caught an error:", error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    this.props.onRetry?.();
  };

  render() {
    if (this.state.hasError) {
      return (
        <ErrorState
          message={this.state.error?.message || "Something went wrong loading this vendor's risk scorecard."}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

export function VendorRiskScorecardPage() {
  const { id } = useParams<{ id: string }>();
  const { data: vendors, loading, reload } = useApi(() => vendorsApi.list(200), []);
  const vendor = vendors?.find((v) => v.id === id) ?? null;

  usePageHeader(vendor ? `${vendor.name} — Risk Scorecard` : "Vendor Risk Scorecard", "Vendors");

  if (!id) {
    return <ErrorState message="Vendor ID is missing." />;
  }

  if (loading && !vendors) return <Skeleton className="h-96" />;

  return (
    <ScorecardErrorBoundary onRetry={reload}>
      <div className="flex flex-col gap-6">
        <VendorRiskScorecard
          vendorId={id}
          vendorName={vendor?.name}
          vendorTier={vendor?.inherent_tier ? `Tier ${vendor.inherent_tier}` : "Tier 1"}
        />
      </div>
    </ScorecardErrorBoundary>
  );
}
