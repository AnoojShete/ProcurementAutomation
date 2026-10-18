import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi } from "@/api/auth";
import { ApiError, endSession, hasSession, setAccessToken, setUnauthorizedHandler } from "@/api/client";
import type { CurrentUser, ThemePreference } from "@/types/api";

interface AuthContextValue {
  user: CurrentUser | null;
  status: "restoring" | "authenticated" | "unauthenticated";
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  /** Saves your own name / theme and refreshes `user`. */
  updateProfile: (changes: { display_name?: string; theme?: ThemePreference }) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthContextValue["status"]>("restoring");

  const logout = useCallback(() => {
    void endSession();
    setAccessToken(null);
    setUser(null);
    setStatus("unauthenticated");
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
      setStatus("unauthenticated");
    });
    return () => setUnauthorizedHandler(null);
  }, []);

  useEffect(() => {
    (async () => {
      if (!hasSession()) {
        setStatus("unauthenticated");
        return;
      }
      try {
        // After a reload the in-memory access token is gone; /auth/me gets a
        // 401 and the client's refresh path uses the session cookie to get a
        // new one.
        const me = await authApi.me();
        setUser(me.data);
        setStatus("authenticated");
      } catch {
        setStatus("unauthenticated");
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    setAccessToken(res.data.access_token);
    try {
      const me = await authApi.me();
      setUser(me.data);
      setStatus("authenticated");
    } catch (e) {
      setAccessToken(null);
      throw e instanceof ApiError ? e : new Error("Unable to load your profile after signing in.");
    }
  }, []);

  const updateProfile = useCallback(async (changes: { display_name?: string; theme?: ThemePreference }) => {
    const res = await authApi.updateMe(changes);
    setUser(res.data);
  }, []);

  const value = useMemo(
    () => ({ user, status, login, logout, updateProfile }),
    [user, status, login, logout, updateProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
