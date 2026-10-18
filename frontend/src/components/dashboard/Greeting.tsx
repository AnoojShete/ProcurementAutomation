import { useAuth } from "@/hooks/useAuth";
import { ROLE_LABELS } from "@/lib/roleNav";

/** Dashboard intro: whose view this is, and today's date. (The page title
 * is already in the top bar.) */
export function Greeting() {
  const { user } = useAuth();
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  return (
    <p className="text-13 text-ink-3">
      {user && (
        <span className="font-medium text-ink-2">
          {user.display_name || user.email} · {ROLE_LABELS[user.role]}
        </span>
      )}
      <span className="ml-3">{today}</span>
    </p>
  );
}
