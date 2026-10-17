import { useAuth } from "@/hooks/useAuth";
import { ROLE_LABELS } from "@/lib/roleNav";

/** Page intro for dashboards: what this view covers, and whose view it is.
 * (The page title itself is already in the top bar.) */
export function Greeting({ subtitle }: { name?: string; subtitle: string }) {
  const { user } = useAuth();
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1">
      <p className="max-w-prose text-body text-ink-2">{subtitle}</p>
      <p className="text-13 text-ink-3">
        {user && <span className="font-medium text-ink-2">{ROLE_LABELS[user.role]} view</span>}
        <span className="ml-3">{today}</span>
      </p>
    </div>
  );
}
