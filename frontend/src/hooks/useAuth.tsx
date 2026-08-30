import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi } from "@/api/auth";
import {
  ApiError,
  getStoredRefreshToken,
  setAccessToken,
  setStoredRefreshToken,
  setUnauthorizedHandler,
} from "@/api/client";
import type { CurrentUser } from "@/types/api";

interface AuthContextValue {
  user: CurrentUser | null;
  status: "restoring" | "authenticated" | "unauthenticated";
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [status, setStatus] = useState<AuthContextValue["status"]>("restoring");

  const logout = useCallback(() => {
    setAccessToken(null);
    setStoredRefreshToken(null);
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
      const refreshToken = getStoredRefreshToken();
      if (!refreshToken) {
        setStatus("unauthenticated");
        return;
      }
      try {
        // /auth/me will trigger the client's own 401->refresh path using the
        // stored refresh token if the (currently empty) in-memory access
        // token is stale, hydrating a real session on reload.
        const me = await authApi.me();
        setUser(me.data);
        setStatus("authenticated");
      } catch {
        setStoredRefreshToken(null);
        setStatus("unauthenticated");
      }
    })();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    setAccessToken(res.data.access_token);
    setStoredRefreshToken(res.data.refresh_token);
    try {
      const me = await authApi.me();
      setUser(me.data);
      setStatus("authenticated");
    } catch (e) {
      setAccessToken(null);
      setStoredRefreshToken(null);
      throw e instanceof ApiError ? e : new Error("Unable to load your profile after signing in.");
    }
  }, []);

  const value = useMemo(() => ({ user, status, login, logout }), [user, status, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
