import { api } from "./client";
import type {
  AccountUser,
  CurrentUser,
  Person,
  Role,
  ThemePreference,
  TokenResponse,
} from "@/types/api";

type Message = { message: string };

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>(
      "/auth/login",
      { email, password },
      { skipAuthRetry: true },
    ),
  me: () => api.get<CurrentUser>("/auth/me"),
  updateMe: (changes: { display_name?: string; theme?: ThemePreference }) =>
    api.patch<CurrentUser>("/auth/me", changes),
  people: () => api.get<Person[]>("/auth/people"),

  register: (email: string, password: string) =>
    api.post<Message>(
      "/auth/register",
      { email, password },
      { skipAuthRetry: true },
    ),
  verifyEmail: (token: string) =>
    api.post<{ verified: boolean; email: string }>(
      "/auth/verify-email",
      { token },
      { skipAuthRetry: true },
    ),
  resendVerification: (email: string) =>
    api.post<Message>(
      "/auth/resend-verification",
      { email },
      { skipAuthRetry: true },
    ),
  forgotPassword: (email: string) =>
    api.post<Message>(
      "/auth/forgot-password",
      { email },
      { skipAuthRetry: true },
    ),
  resetPassword: (token: string, newPassword: string) =>
    api.post<Message>(
      "/auth/reset-password",
      { token, new_password: newPassword },
      { skipAuthRetry: true },
    ),
  changePassword: (currentPassword: string, newPassword: string) =>
    api.post<TokenResponse>("/auth/change-password", {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  logoutEverywhere: () => api.post<{ signed_out: boolean }>("/auth/logout-all"),

  listUsers: (q?: string) =>
    api.get<AccountUser[]>(
      `/auth/users${q ? `?q=${encodeURIComponent(q)}` : ""}`,
    ),
  getUser: (id: string) => api.get<AccountUser>(`/auth/users/${id}`),
  updateUser: (
    id: string,
    changes: { email?: string; role?: Role; is_active?: boolean },
  ) => api.patch<AccountUser>(`/auth/users/${id}`, changes),
  getDemoAccounts: () =>
    api.get<{ role: string; email: string; display_name: string | null }[]>(
      "/auth/demo-accounts",
      { skipAuthRetry: true },
    ),
};

/** Reads the one-time token from the link's "#token=..." and removes it
 * from the address bar, so it isn't left in history or shared by accident. */
export function takeTokenFromUrl(): string | null {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = params.get("token");
  if (token) window.history.replaceState(null, "", window.location.pathname);
  return token;
}
