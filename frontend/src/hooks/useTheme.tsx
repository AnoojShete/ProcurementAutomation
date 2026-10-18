import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { useAuth } from "@/hooks/useAuth";
import type { ThemePreference } from "@/types/api";

// Same key as public/theme-init.js, which applies it before first paint.
const STORAGE_KEY = "procurement.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function stored(): ThemePreference {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function remember(pref: ThemePreference) {
  try {
    localStorage.setItem(STORAGE_KEY, pref);
  } catch {
    // Private mode: the account still has it.
  }
}

function apply(pref: ThemePreference) {
  const dark = pref === "dark" || (pref === "system" && window.matchMedia(DARK_QUERY).matches);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
}

interface ThemeContextValue {
  preference: ThemePreference;
  setPreference: (pref: ThemePreference) => Promise<void>;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

/** The theme is saved on the account (auth-service `theme`), so it follows
 * the person across sessions and devices; localStorage only covers the
 * moments before sign-in. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const { user, updateProfile } = useAuth();
  const [preference, setLocal] = useState<ThemePreference>(stored);

  // Signing in brings the account's saved choice.
  useEffect(() => {
    if (user?.theme) {
      setLocal(user.theme);
      remember(user.theme);
    }
  }, [user?.id, user?.theme]);

  useEffect(() => {
    apply(preference);
    if (preference !== "system") return;
    const mq = window.matchMedia(DARK_QUERY);
    const onChange = () => apply("system");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [preference]);

  const setPreference = useCallback(
    async (pref: ThemePreference) => {
      setLocal(pref);
      remember(pref);
      if (user) await updateProfile({ theme: pref });
    },
    [user, updateProfile],
  );

  return <ThemeContext.Provider value={{ preference, setPreference }}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
