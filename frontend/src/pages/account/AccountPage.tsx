import { useState } from "react";
import { authApi } from "@/api/auth";
import { ApiError, setAccessToken } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { PASSWORD_HINT, PasswordField } from "@/components/auth/AuthLayout";
import { ROLE_LABELS } from "@/lib/roleNav";

export function AccountPage() {
  usePageHeader("Account");
  const { user, logout } = useAuth();
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
        <CardBody>
          <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-sm">
            <dt className="text-slate-500">Email</dt>
            <dd className="text-slate-900">{user.email}</dd>
            <dt className="text-slate-500">Role</dt>
            <dd className="text-slate-900">{ROLE_LABELS[user.role]}</dd>
          </dl>
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
          <p className="text-sm text-slate-600">
            Signed in on a shared or lost device? Sign out everywhere, including
            here.
          </p>
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
