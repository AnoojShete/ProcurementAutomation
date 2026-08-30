import { useAuth } from "@/hooks/useAuth";
import { RequesterDashboard } from "./RequesterDashboard";
import { ApproverDashboard } from "./ApproverDashboard";
import { FinanceDashboard } from "./FinanceDashboard";
import { AdminDashboard } from "./AdminDashboard";

export function DashboardPage() {
  const { user } = useAuth();
  if (!user) return null;
  switch (user.role) {
    case "requester":
      return <RequesterDashboard />;
    case "approver":
      return <ApproverDashboard />;
    case "finance":
      return <FinanceDashboard />;
    case "admin":
      return <AdminDashboard />;
  }
}
