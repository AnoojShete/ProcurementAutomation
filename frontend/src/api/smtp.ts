import { api } from "./client";

export interface SmtpSettings {
  host: string;
  port: number;
  emailFrom: string;
  username: string;
  password?: string;
  enableSsl: boolean;
  hasPassword?: boolean;
}

export interface SmtpSaveResponse {
  message: string;
  success?: boolean;
}

export interface SmtpTestResponse {
  message: string;
  success: boolean;
}

export const smtpApi = {
  getSettings: () => api.get<SmtpSettings>("/SmtpSettings/GetSettings"),
  saveSettings: (settings: SmtpSettings) => api.post<SmtpSaveResponse>("/SmtpSettings/SaveSettings", settings),
  testConnection: (settings: SmtpSettings) => api.post<SmtpTestResponse>("/SmtpSettings/TestConnection", settings),
};
