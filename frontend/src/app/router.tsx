import { lazy, Suspense } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ProtectedRoute } from "./ProtectedRoute";
import { RoleGuard } from "./RoleGuard";
import { AppShell } from "@/layouts/AppShell";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

const DashboardPage = lazy(() => import("@/pages/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const RequestsListPage = lazy(() => import("@/pages/requests/RequestsListPage").then((m) => ({ default: m.RequestsListPage })));
const NewRequestWizardPage = lazy(() => import("@/pages/requests/NewRequestWizardPage").then((m) => ({ default: m.NewRequestWizardPage })));
const RequestDetailPage = lazy(() => import("@/pages/requests/RequestDetailPage").then((m) => ({ default: m.RequestDetailPage })));
const DocumentsListPage = lazy(() => import("@/pages/documents/DocumentsListPage").then((m) => ({ default: m.DocumentsListPage })));
const DocumentDetailPage = lazy(() => import("@/pages/documents/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage })));
const VendorsListPage = lazy(() => import("@/pages/vendors/VendorsListPage").then((m) => ({ default: m.VendorsListPage })));
const VendorDetailPage = lazy(() => import("@/pages/vendors/VendorDetailPage").then((m) => ({ default: m.VendorDetailPage })));
const ApprovalInboxPage = lazy(() => import("@/pages/approvals/ApprovalInboxPage").then((m) => ({ default: m.ApprovalInboxPage })));
const InventoryPage = lazy(() => import("@/pages/inventory/InventoryPage").then((m) => ({ default: m.InventoryPage })));
const ContractsListPage = lazy(() => import("@/pages/contracts/ContractsListPage").then((m) => ({ default: m.ContractsListPage })));
const ContractDetailPage = lazy(() => import("@/pages/contracts/ContractDetailPage").then((m) => ({ default: m.ContractDetailPage })));
const RiskDashboardPage = lazy(() => import("@/pages/risk/RiskDashboardPage").then((m) => ({ default: m.RiskDashboardPage })));
const NotificationsPage = lazy(() => import("@/pages/notifications/NotificationsPage").then((m) => ({ default: m.NotificationsPage })));
const SpendAnalysisPage = lazy(() => import("@/pages/finance/SpendAnalysisPage").then((m) => ({ default: m.SpendAnalysisPage })));
const AuditActivityPage = lazy(() => import("@/pages/admin/AuditActivityPage").then((m) => ({ default: m.AuditActivityPage })));
const SystemHealthPage = lazy(() => import("@/pages/admin/SystemHealthPage").then((m) => ({ default: m.SystemHealthPage })));

function Loading() {
  return (
    <div className="flex h-64 items-center justify-center">
      <div className="size-6 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
    </div>
  );
}

function withSuspense(el: React.ReactNode) {
  return <Suspense fallback={<Loading />}>{el}</Suspense>;
}

const router = createBrowserRouter([
  { path: "/", element: <Navigate to="/app" replace /> },
  { path: "/login", element: <LoginPage /> },
  {
    path: "/app",
    element: (
      <ProtectedRoute>
        <AppShell />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: withSuspense(<DashboardPage />) },
      { path: "requests", element: withSuspense(<RequestsListPage />) },
      {
        path: "requests/new",
        element: withSuspense(
          <RoleGuard allow={["requester", "admin"]}>
            <NewRequestWizardPage />
          </RoleGuard>,
        ),
      },
      { path: "requests/:id", element: withSuspense(<RequestDetailPage />) },
      { path: "documents", element: withSuspense(<DocumentsListPage />) },
      { path: "documents/:id", element: withSuspense(<DocumentDetailPage />) },
      { path: "vendors", element: withSuspense(<VendorsListPage />) },
      { path: "vendors/:id", element: withSuspense(<VendorDetailPage />) },
      {
        path: "approvals",
        element: withSuspense(
          <RoleGuard allow={["approver", "finance", "admin"]}>
            <ApprovalInboxPage />
          </RoleGuard>,
        ),
      },
      {
        path: "inventory",
        element: withSuspense(
          <RoleGuard allow={["admin"]}>
            <InventoryPage />
          </RoleGuard>,
        ),
      },
      {
        path: "contracts",
        element: withSuspense(
          <RoleGuard allow={["finance", "admin", "approver"]}>
            <ContractsListPage />
          </RoleGuard>,
        ),
      },
      {
        path: "contracts/:id",
        element: withSuspense(
          <RoleGuard allow={["finance", "admin", "approver"]}>
            <ContractDetailPage />
          </RoleGuard>,
        ),
      },
      {
        path: "risk",
        element: withSuspense(
          <RoleGuard allow={["finance", "admin"]}>
            <RiskDashboardPage />
          </RoleGuard>,
        ),
      },
      { path: "notifications", element: withSuspense(<NotificationsPage />) },
      {
        path: "spend",
        element: withSuspense(
          <RoleGuard allow={["finance", "admin"]}>
            <SpendAnalysisPage />
          </RoleGuard>,
        ),
      },
      {
        path: "audit",
        element: withSuspense(
          <RoleGuard allow={["admin"]}>
            <AuditActivityPage />
          </RoleGuard>,
        ),
      },
      {
        path: "system-health",
        element: withSuspense(
          <RoleGuard allow={["admin"]}>
            <SystemHealthPage />
          </RoleGuard>,
        ),
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
