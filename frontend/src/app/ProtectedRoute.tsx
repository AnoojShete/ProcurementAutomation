import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "restoring") {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-subtle">
        <div className="size-8 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      </div>
    );
  }
  if (status === "unauthenticated") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }
  return <>{children}</>;
}
