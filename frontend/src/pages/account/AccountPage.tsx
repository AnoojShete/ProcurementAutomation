import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { authApi } from "@/api/auth";
import { ApiError, setAccessToken } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { cn } from "@/lib/cn";
import type { ThemePreference } from "@/types/api";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { PASSWORD_HINT, PasswordField } from "@/components/auth/AuthLayout";
import { ROLE_LABELS } from "@/lib/roleNav";

const THEMES: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "Match device", icon: Monitor },
];

export function AccountPage() {
  usePageHeader("Account settings");
  const { user, logout, updateProfile } = useAuth();
  const { preference, setPreference } = useTheme();
  const [themeError, setThemeError] = useState<string | null>(null);
  const [name, setName] = useState(user?.display_name ?? "");
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState<string | null>(null);
  const [nameSaved, setNameSaved] = useState(false);
  useEffect(() => setName(user?.display_name ?? ""), [user?.display_name]);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  if (!user) return null;

  const changePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSaved(false);
    if (next !== confirm) return setError("The two new passwords don't match.");
    setSaving(true);
    try {
      const res = await authApi.changePassword(current, next);
      // Other devices are signed out; this one gets a fresh session.
      setAccessToken(res.data.access_token);
      setSaved(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Couldn't change the password.",
      );
    } finally {
      setSaving(false);
    }
  };

  const chooseTheme = async (pref: ThemePreference) => {
    setThemeError(null);
    try {
      await setPreference(pref);
    } catch (e) {
      setThemeError(e instanceof ApiError ? e.message : "Couldn't save the theme to your account.");
    }
  };

  const saveName = async (e: React.FormEvent) => {
    e.preventDefault();
    setNameError(null);
    setNameSaved(false);
    setNameSaving(true);
    try {
      await updateProfile({ display_name: name });
      setNameSaved(true);
    } catch (e) {
      setNameError(e instanceof ApiError ? e.message : "Couldn't save your name.");
    } finally {
      setNameSaving(false);
    }
  };

  const signOutEverywhere = async () => {
    setSigningOut(true);
    try {
      await authApi.logoutEverywhere();
    } finally {
      logout();
    }
  };

  return (
    <div className="max-w-xl space-y-4">
      <Card>
        <CardHeader title="Profile" />
        <CardBody className="space-y-4">
          <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-sm">
            <dt className="text-ink-3">Email</dt>
            <dd className="text-ink">{user.email}</dd>
            <dt className="text-ink-3">Role</dt>
            <dd className="text-ink">{ROLE_LABELS[user.role]}</dd>
          </dl>
          <form onSubmit={saveName} className="flex flex-wrap items-end gap-2" noValidate>
            <label className="min-w-0 flex-1 text-13 text-ink-2">
              Name
              <input className="field mt-1" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </label>
            <Button type="submit" variant="secondary" loading={nameSaving} disabled={!name.trim() || name.trim() === user.display_name}>
              Save
            </Button>
          </form>
          {nameError && <InlineError message={nameError} />}
          {nameSaved && <InlineSuccess message="Name saved." />}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Appearance" />
        <CardBody className="space-y-3">
          <div role="radiogroup" aria-label="Theme" className="inline-flex rounded border border-rule-strong p-0.5">
            {THEMES.map((t) => (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={preference === t.value}
                onClick={() => void chooseTheme(t.value)}
                className={cn(
                  "flex h-8 items-center gap-1.5 rounded-sm px-3 text-13 transition-colors duration-1",
                  preference === t.value ? "bg-accent-tint font-medium text-ink" : "text-ink-2 hover:bg-sheet-sunk hover:text-ink",
                )}
              >
                <t.icon className="size-3.5" strokeWidth={1.75} aria-hidden="true" />
                {t.label}
              </button>
            ))}
          </div>
          {themeError && <InlineError message={themeError} />}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Change password"
          subtitle="Other devices will be signed out."
        />
        <CardBody>
          <form onSubmit={changePassword} className="space-y-3" noValidate>
            {error && <InlineError message={error} />}
            {saved && (
              <InlineSuccess message="Password changed. We've emailed you a confirmation." />
            )}
            <PasswordField
              id="current"
              label="Current password"
              value={current}
              onChange={setCurrent}
              autoComplete="current-password"
            />
            <PasswordField
              id="new"
              label="New password"
              value={next}
              onChange={setNext}
              autoComplete="new-password"
              hint={PASSWORD_HINT}
            />
            <PasswordField
              id="confirm"
              label="Confirm new password"
              value={confirm}
              onChange={setConfirm}
              autoComplete="new-password"
            />
            <Button
              type="submit"
              loading={saving}
              disabled={!current || !next || !confirm}
            >
              Change password
            </Button>
          </form>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Sessions" />
        <CardBody className="flex items-center justify-between gap-4">
          <p className="text-sm text-ink-2">Signs out every device, including this one.</p>
          <Button
            variant="secondary"
            loading={signingOut}
            onClick={signOutEverywhere}
          >
            Sign out everywhere
          </Button>
        </CardBody>
      </Card>
    </div>
  );
}
