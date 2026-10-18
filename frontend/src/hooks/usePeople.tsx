import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi } from "@/api/auth";
import type { Person } from "@/types/api";

interface PeopleContextValue {
  /** The account behind an email, if there is one. */
  personFor: (email: string | null | undefined) => Person | undefined;
  /** Display name for an email; the email itself when there's no name. */
  nameFor: (email: string | null | undefined, fallback?: string) => string;
  /** Replaces every known email inside a sentence (notification subjects,
   * activity lines) with the person's name. */
  withNames: (text: string | null | undefined) => string;
}

const PeopleContext = createContext<PeopleContextValue | null>(null);

const EMAIL_RE = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

/** Requests, approvals and logs store people by email; this loads the
 * directory once (GET /auth/people) so pages can show names instead. */
export function PeopleProvider({ children }: { children: ReactNode }) {
  const [people, setPeople] = useState<Person[]>([]);

  useEffect(() => {
    authApi
      .people()
      .then((r) => setPeople(r.data))
      .catch(() => setPeople([])); // names fall back to emails
  }, []);

  const byEmail = useMemo(() => new Map(people.map((p) => [p.email.toLowerCase(), p])), [people]);
  const personFor = useCallback((email: string | null | undefined) => (email ? byEmail.get(email.toLowerCase()) : undefined), [byEmail]);
  const nameFor = useCallback(
    (email: string | null | undefined, fallback = "—") => {
      if (!email) return fallback;
      return personFor(email)?.display_name || email;
    },
    [personFor],
  );
  const withNames = useCallback(
    (text: string | null | undefined) => (text ? text.replace(EMAIL_RE, (m) => personFor(m)?.display_name || m) : ""),
    [personFor],
  );

  const value = useMemo(() => ({ personFor, nameFor, withNames }), [personFor, nameFor, withNames]);
  return <PeopleContext.Provider value={value}>{children}</PeopleContext.Provider>;
}

const FALLBACK: PeopleContextValue = {
  personFor: () => undefined,
  nameFor: (email, fallback = "—") => email || fallback,
  withNames: (text) => text ?? "",
};

export function usePeople(): PeopleContextValue {
  return useContext(PeopleContext) ?? FALLBACK;
}
