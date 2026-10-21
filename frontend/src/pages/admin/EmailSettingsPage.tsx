import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { Mail, CheckCircle2, AlertCircle, Save, Server, ArrowLeft, RefreshCw } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { smtpApi, type SmtpSettings } from "@/api/smtp";
import { ApiError } from "@/api/client";

type SmtpProvider = "custom" | "gmail" | "outlook" | "yahoo" | "zoho";
type SecurityMode = "ssl" | "none";

interface EmailSettingsProps {
  onBack?: () => void;
}

const providerConfig: Record<Exclude<SmtpProvider, "custom">, { host: string; port: number; enableSsl: boolean }> = {
  gmail: { host: "smtp.gmail.com", port: 587, enableSsl: true },
  outlook: { host: "smtp.office365.com", port: 587, enableSsl: true },
  yahoo: { host: "smtp.mail.yahoo.com", port: 465, enableSsl: true },
  zoho: { host: "smtp.zoho.com", port: 465, enableSsl: true },
};

const detectProvider = (host: string): SmtpProvider => {
  const normalizedHost = (host || "").toLowerCase();
  if (normalizedHost.includes("gmail")) return "gmail";
  if (normalizedHost.includes("office365") || normalizedHost.includes("outlook")) return "outlook";
  if (normalizedHost.includes("yahoo")) return "yahoo";
  if (normalizedHost.includes("zoho")) return "zoho";
  return "custom";
};

export function EmailSettingsPage({ onBack }: EmailSettingsProps) {
  usePageHeader("Email Integrations", "Administration");
  const navigate = useNavigate();

  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [fetching, setFetching] = useState(true);
  const [smtpProvider, setSmtpProvider] = useState<SmtpProvider>("custom");
  const [securityMode, setSecurityMode] = useState<SecurityMode>("ssl");
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const [settings, setSettings] = useState<SmtpSettings>({
    host: "",
    port: 587,
    emailFrom: "",
    username: "",
    password: "",
    enableSsl: true,
    hasPassword: false,
  });

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setFetching(true);
    setStatusMessage(null);
    try {
      const response = await smtpApi.getSettings();
      const data = response.data;
      if (data && data.host) {
        const detected = detectProvider(data.host);
        setSmtpProvider(detected);
        setSecurityMode(data.enableSsl ? "ssl" : "none");
        setSettings((prev) => ({
          ...prev,
          ...data,
          port: Number(data.port) || 587,
          enableSsl: Boolean(data.enableSsl),
          password: "",
        }));
      }
    } catch (error) {
      console.error("Failed to load SMTP settings:", error);
    } finally {
      setFetching(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    const checked = (e.target as HTMLInputElement).checked;
    setSettings((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : name === "port" ? parseInt(value) || 0 : value,
    }));
  };

  const handleProviderChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as SmtpProvider;
    setSmtpProvider(value);
    if (value === "custom") return;

    const cfg = providerConfig[value];
    setSettings((prev) => ({
      ...prev,
      host: cfg.host,
      port: cfg.port,
      enableSsl: cfg.enableSsl,
    }));
    setSecurityMode(cfg.enableSsl ? "ssl" : "none");
  };

  const handleSecurityModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value as SecurityMode;
    setSecurityMode(value);
    setSettings((prev) => ({
      ...prev,
      enableSsl: value === "ssl",
    }));
  };

  const handleBack = () => {
    if (onBack) {
      onBack();
      return;
    }
    navigate("/app/control-panel");
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatusMessage(null);
    setLoading(true);

    try {
      if (!settings.host || !settings.emailFrom || !settings.username) {
        setStatusMessage({ type: "error", text: "Please fill in all required fields (Host, Sender Email, Username)." });
        setLoading(false);
        return;
      }

      if (!settings.hasPassword && !settings.password) {
        setStatusMessage({ type: "error", text: "Password is required for first-time SMTP setup." });
        setLoading(false);
        return;
      }

      const res = await smtpApi.saveSettings(settings);
      setStatusMessage({ type: "success", text: res.data?.message || "SMTP settings saved successfully!" });
      await fetchSettings();
    } catch (error) {
      const msg = error instanceof ApiError ? error.message : "Failed to save SMTP settings.";
      setStatusMessage({ type: "error", text: msg });
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const handleTest = async () => {
    setStatusMessage(null);
    setTesting(true);
    try {
      const payload: SmtpSettings = {
        ...settings,
        port: Number(settings.port),
        enableSsl: Boolean(settings.enableSsl),
      };

      const res = await smtpApi.testConnection(payload);
      if (res.data?.success) {
        setStatusMessage({ type: "success", text: res.data.message || "Connection Successful!" });
      } else {
        setStatusMessage({ type: "error", text: res.data?.message || "Connection Failed." });
      }
    } catch (error) {
      const msg = error instanceof ApiError ? error.message : "Connection failed. Please check host, port and credentials.";
      setStatusMessage({ type: "error", text: msg });
      console.error(error);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 p-4 sm:p-6">
      {/* Back Button */}
      <div>
        <button
          type="button"
          onClick={handleBack}
          className="inline-flex items-center gap-2 text-sm font-medium text-ink-3 transition-colors hover:text-ink"
        >
          <ArrowLeft className="size-4" />
          <span>Back to Control Panel</span>
        </button>
      </div>

      {/* Header */}
      <div className="flex flex-col gap-1">
        <h1 className="flex items-center gap-3 text-2xl font-bold text-ink sm:text-3xl">
          <Mail className="size-7 text-accent" />
          Email Integrations
        </h1>
        <p className="text-sm text-ink-2">
          Configure your custom SMTP server to send platform notifications from your company domain.
        </p>
      </div>

      {/* Status Messages */}
      {statusMessage && (
        <div
          className={`flex items-start gap-3 rounded border p-4 text-sm ${
            statusMessage.type === "success"
              ? "border-success-200 bg-success-50 text-success-800"
              : "border-danger-200 bg-danger-50 text-danger-800"
          }`}
        >
          {statusMessage.type === "success" ? (
            <CheckCircle2 className="size-5 shrink-0 text-success-600" />
          ) : (
            <AlertCircle className="size-5 shrink-0 text-danger-600" />
          )}
          <div>{statusMessage.text}</div>
        </div>
      )}

      {/* Main Settings Card */}
      <Card>
        <CardHeader
          title="SMTP Configuration"
          subtitle="All emails dispatched by the platform will route through this mail server."
          action={
            <Button
              variant="secondary"
              size="sm"
              icon={<RefreshCw className={`size-3.5 ${fetching ? "animate-spin" : ""}`} />}
              onClick={fetchSettings}
              disabled={fetching}
            >
              Refresh
            </Button>
          }
        />
        <CardBody>
          <form onSubmit={handleSave} className="flex flex-col gap-5">
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
              {/* Provider Selection */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">SMTP Provider</span>
                <select
                  value={smtpProvider}
                  onChange={handleProviderChange}
                  className="field"
                >
                  <option value="custom">Custom SMTP</option>
                  <option value="gmail">Gmail</option>
                  <option value="outlook">Outlook / Office365</option>
                  <option value="yahoo">Yahoo Mail</option>
                  <option value="zoho">Zoho Mail</option>
                </select>
              </label>

              {/* Host */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">SMTP Host</span>
                <input
                  name="host"
                  type="text"
                  placeholder="e.g. smtp.gmail.com"
                  value={settings.host}
                  onChange={handleChange}
                  className="field font-mono"
                  required
                />
              </label>

              {/* Port */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">Port</span>
                <input
                  name="port"
                  type="number"
                  placeholder="587"
                  value={settings.port || ""}
                  onChange={handleChange}
                  className="field font-mono"
                  required
                />
              </label>

              {/* Security Mode */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">Connection Security</span>
                <select
                  value={securityMode}
                  onChange={handleSecurityModeChange}
                  className="field"
                >
                  <option value="ssl">SSL / TLS (Recommended)</option>
                  <option value="none">None (Plaintext)</option>
                </select>
              </label>

              {/* Sender Email (From) */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">Sender Email (From)</span>
                <input
                  name="emailFrom"
                  type="email"
                  placeholder="notifications@yourcompany.com"
                  value={settings.emailFrom}
                  onChange={handleChange}
                  className="field"
                  required
                />
              </label>

              {/* Username */}
              <label className="flex flex-col gap-1 text-13 text-ink-2">
                <span className="font-medium text-ink">Username</span>
                <input
                  name="username"
                  type="text"
                  placeholder="Usually your login email"
                  value={settings.username}
                  onChange={handleChange}
                  className="field"
                  required
                />
              </label>

              {/* Password */}
              <div className="flex flex-col gap-1 text-13 text-ink-2 md:col-span-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium text-ink">Password</span>
                  {settings.hasPassword && (
                    <span className="text-xs font-semibold text-success-700">
                      (Password is securely stored and encrypted)
                    </span>
                  )}
                </div>
                <input
                  name="password"
                  type="password"
                  placeholder={
                    settings.hasPassword
                      ? "•••••••• (Leave blank to keep current encrypted password)"
                      : "Enter SMTP App Password or API Key"
                  }
                  value={settings.password}
                  onChange={handleChange}
                  className="field font-mono"
                />
                <span className="text-12 text-ink-3">
                  Passwords are encrypted using AES-256-GCM before storage in the database.
                </span>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-rule pt-4">
              <Button
                type="button"
                variant="secondary"
                onClick={handleTest}
                disabled={testing || !settings.host}
                loading={testing}
                icon={<CheckCircle2 className="size-4" />}
              >
                Test Connection
              </Button>

              <Button
                type="submit"
                variant="primary"
                loading={loading}
                icon={<Save className="size-4" />}
              >
                Save Settings
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>

      {/* Info note */}
      <div className="flex items-start gap-3 rounded border border-rule bg-sheet-sunk p-4 text-sm text-ink-2">
        <AlertCircle className="mt-0.5 size-5 shrink-0 text-accent" />
        <div className="flex flex-col gap-1">
          <span className="font-semibold text-ink">Default Mailer Fallback:</span>
          <span>
            If custom SMTP settings are not configured or inactive, the platform automatically falls back to the system
            mailer (Mailpit in development, standard environment SMTP in production).
          </span>
        </div>
      </div>
    </div>
  );
}

export default EmailSettingsPage;
