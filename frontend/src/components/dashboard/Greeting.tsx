import { useAuth } from "@/hooks/useAuth";
import { ROLE_LABELS } from "@/lib/roleNav";

/** Page intro for dashboards: what this view covers, and whose view it is.
 * (The page title itself is already in the top bar.) */
export function Greeting({ subtitle }: { name?: string; subtitle: string }) {
  const { user } = useAuth();
  const today = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return (
    <div className="flex flex-wrap items-end justify-between gap-2 border-b border-surface-border pb-3">
      <p className="text-sm text-slate-600">{subtitle}</p>
      <p className="text-xs text-slate-500">
        {user ? `${ROLE_LABELS[user.role]} view · ` : ""}
        {today}
      </p>
    </div>
  );
}
