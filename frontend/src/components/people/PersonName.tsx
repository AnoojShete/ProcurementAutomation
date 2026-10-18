import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { usePeople } from "@/hooks/usePeople";

/** A person's name where the data holds their email. Plain text; for an
 * admin it opens that person's profile (no link styling, the email is in
 * the tooltip). */
export function PersonName({ email, fallback = "—" }: { email: string | null | undefined; fallback?: string }) {
  const { user } = useAuth();
  const { personFor, nameFor } = usePeople();
  const person = personFor(email);
  const name = nameFor(email, fallback);
  if (!person || user?.role !== "admin") return <span title={email ?? undefined}>{name}</span>;
  return (
    <Link
      to={person.id === user.id ? "/app/account" : `/app/users/${person.id}`}
      title={email ?? undefined}
      onClick={(e) => e.stopPropagation()}
      className="text-inherit no-underline hover:text-inherit"
    >
      {name}
    </Link>
  );
}
