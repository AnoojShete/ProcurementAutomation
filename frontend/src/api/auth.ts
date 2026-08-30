import { api } from "./client";
import type { CurrentUser, TokenResponse } from "@/types/api";

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>("/auth/login", { email, password }, { skipAuthRetry: true }),
  me: () => api.get<CurrentUser>("/auth/me"),
};
