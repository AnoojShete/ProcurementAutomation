import type { ReactNode } from "react";
import { ShieldOff } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import type { Role } from "@/types/api";

/**
 * Route-level convenience only — the backend's `require_role` dependency on
 * each endpoint is the real enforcement. This exists so a user never lands
 * on a page shaped for a role they don't have (wrong nav context, actions
 * that would just 403), not as a security boundary.
 */
export function RoleGuard({ allow, children }: { allow: Role[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return null;
  if (!allow.includes(user.role)) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-surface-border bg-white py-16 text-center shadow-card">
        <ShieldOff className="size-8 text-slate-300" />
        <p className="text-sm font-medium text-slate-700">This area isn't part of your role</p>
        <p className="max-w-sm text-sm text-slate-500">
          Your account is signed in as <span className="font-medium">{user.role}</span>. This page is for a
          different role — use the navigation for what's available to you.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}
