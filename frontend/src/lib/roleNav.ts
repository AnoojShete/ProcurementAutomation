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
  Sliders as SL,
  ShieldCheck as SC2,
  Users as US,
  Radio as RA,
  Settings2 as SE,
  Wallet as WA,
  ShoppingCart as SCART,
  Scale as SCALE,
} from "lucide-react";
import type { Role } from "@/types/api";

export type IconType = typeof LD;

export interface NavItem {
  label: string;
  to: string;
  icon: IconType;
  end?: boolean;
  /** Other paths that count as this item (pages reached from it). */
  match?: string[];
}

export interface SystemSection {
  label: string;
  to: string;
  icon: IconType;
  description: string;
}

/** Admin system management: one landing page (/app/system) with a card
 * per section; each section keeps its own page. */
export const SYSTEM_SECTIONS: SystemSection[] = [
  { label: "System Health", to: "/app/system-health", icon: HP, description: "Services, consumer lag, live verification" },
  { label: "Users", to: "/app/users", icon: US, description: "Accounts, roles, access" },
  { label: "Controls", to: "/app/controls", icon: SC2, description: "Event reliability, authority, payments, matching" },
  { label: "Control Panel", to: "/app/control-panel", icon: RA, description: "Drop folder, Kafka events, storage, e-sign" },
  { label: "Business Rules", to: "/app/business-rules", icon: SL, description: "Spend tiers, SLAs, thresholds" },
  { label: "Audit & Activity", to: "/app/audit", icon: CL, description: "Activity across requests and contracts" },
];

const dashboard = (to: string): NavItem => ({ label: "Dashboard", to, icon: LD, end: true });

export const ROLE_NAV: Record<Role, NavItem[]> = {
  requester: [
    dashboard("/app"),
    { label: "My Requests", to: "/app/requests", icon: FT },
    { label: "New Request", to: "/app/requests/new", icon: FP },
    { label: "IT Catalog", to: "/app/catalog", icon: SCART },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  approver: [
    dashboard("/app"),
    { label: "Approval Inbox", to: "/app/approvals", icon: IN },
    { label: "Licenses", to: "/app/licenses", icon: BO },
    { label: "Requests", to: "/app/requests", icon: FT },
    { label: "Budgets", to: "/app/budgets", icon: WA },
    { label: "Sourcing", to: "/app/sourcing", icon: SCALE },
    { label: "IT Catalog", to: "/app/catalog", icon: SCART },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  finance: [
    dashboard("/app"),
    { label: "Approval Queue", to: "/app/approvals", icon: IN },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Licenses", to: "/app/licenses", icon: BO },
    { label: "Budgets", to: "/app/budgets", icon: WA },
    { label: "Sourcing", to: "/app/sourcing", icon: SCALE },
    { label: "IT Catalog", to: "/app/catalog", icon: SCART },
    { label: "Spend Analysis", to: "/app/spend", icon: AC },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Contracts", to: "/app/contracts", icon: SC },
    { label: "Risk", to: "/app/risk", icon: SH },
    { label: "Controls", to: "/app/controls", icon: SC2 },
    { label: "Notifications", to: "/app/notifications", icon: BE },
  ],
  admin: [
    { label: "Overview", to: "/app", icon: LD, end: true },
    { label: "Licenses", to: "/app/licenses", icon: BO },
    { label: "Requests", to: "/app/requests", icon: FT },
    { label: "Documents", to: "/app/documents", icon: FI },
    { label: "Vendors", to: "/app/vendors", icon: BU },
    { label: "Approvals", to: "/app/approvals", icon: IN },
    { label: "Budgets", to: "/app/budgets", icon: WA },
    { label: "Sourcing", to: "/app/sourcing", icon: SCALE },
    { label: "IT Catalog", to: "/app/catalog", icon: SCART },
    { label: "Inventory", to: "/app/inventory", icon: BO },
    { label: "Contracts", to: "/app/contracts", icon: SC },
    { label: "Risk", to: "/app/risk", icon: SH },
    { label: "Notifications", to: "/app/notifications", icon: BE },
    { label: "System", to: "/app/system", icon: SE, match: SYSTEM_SECTIONS.map((s) => s.to) },
  ],
};

export const ROLE_LABELS: Record<Role, string> = {
  requester: "Requester",
  approver: "Approver",
  finance: "Finance",
  admin: "Administrator",
};
