import {
  LayoutDashboard as LD,
  FileText as FT,
  FilePlus2 as FP,
  Files as FI,
  Building2 as BU,
  Bell as BE,
  Inbox as IN,
  ScrollText as SC,
  ShieldAlert as SH,
  Boxes as BO,
  ClipboardList as CL,
  Activity as AC,
  HeartPulse as HP,
} from "lucide-react";
import type { Role } from "@/types/api";

export type IconType = typeof LD;

export interface NavItem {
  label: string;
  to: string;
  icon: IconType;
  end?: boolean;
}

const dashboard = (to: string): NavItem => ({ label: "Dashboard", to, icon: LD, end: true });

export const ROLE_NAV: Record<Role, NavItem[]> = {
  requester: [
    dashboard("/app"),
    { label: "My Requests", to: "/app/requests", icon: FT },
    { label: "New Request", to: "/app/requests/new", icon: FP },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  approver: [
    dashboard("/app"),
    { label: "Approval Inbox", to: "/app/approvals", icon: IN },
    { label: "Requests", to: "/app/requests", icon: FT },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  finance: [
    dashboard("/app"),
    { label: "Approval Queue", to: "/app/approvals", icon: IN },
    { label: "Spend Analysis", to: "/app/spend", icon: AC },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Contracts", to: "/app/contracts", icon: SC },
    { label: "Risk", to: "/app/risk", icon: SH },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  admin: [
    { label: "Overview", to: "/app", icon: LD, end: true },
    { label: "Requests", to: "/app/requests", icon: FT },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Approvals", to: "/app/approvals", icon: IN },
    { label: "Inventory", to: "/app/inventory", icon: BO },
    { label: "Contracts", to: "/app/contracts", icon: SC },
    { label: "Risk", to: "/app/risk", icon: SH },
    { label: "Notifications", to: "/app/notifications", icon: BE },
    { label: "Audit & Activity", to: "/app/audit", icon: CL },
    { label: "System Health", to: "/app/system-health", icon: HP },
  ],
};

export const ROLE_LABELS: Record<Role, string> = {
  requester: "Requester",
  approver: "Approver",
  finance: "Finance",
  admin: "Administrator",
};
