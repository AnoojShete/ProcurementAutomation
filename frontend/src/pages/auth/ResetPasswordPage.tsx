import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { authApi, takeTokenFromUrl } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import {
  AuthLayout,
  PASSWORD_HINT,
  PasswordField,
} from "@/components/auth/AuthLayout";

/** Opened from the reset email (/reset-password#token=…). */
export function ResetPasswordPage() {
  const token = useRef<string | null>(takeTokenFromUrl());
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const footer = (
    <Link to="/login" className="font-medium text-brand-700 hover:underline">
      Back to sign in
    </Link>
  );

  if (!token.current && !done)
    return (
      <AuthLayout title="Reset your password" footer={footer}>
        <InlineError message="This page needs the link from your reset email." />
        <Link to="/forgot-password" className="block">
          <Button variant="secondary" className="w-full">
            Request a reset link
          </Button>
        </Link>
      </AuthLayout>
    );

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("The two passwords don't match.");
    setSaving(true);
    try {
      setDone(
        (await authApi.resetPassword(token.current!, password)).data.message,
      );
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Couldn't reset the password. Please try again.",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <AuthLayout title="Choose a new password" footer={footer}>
      {done ? (
        <>
          <InlineSuccess message={done} />
          <Link to="/login" className="block">
            <Button className="w-full">Sign in</Button>
          </Link>
        </>
      ) : (
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          {error && <InlineError message={error} />}
          <PasswordField
            id="password"
            label="New password"
            value={password}
            onChange={setPassword}
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
            className="w-full"
            loading={saving}
            disabled={!password || !confirm}
          >
            Set new password
          </Button>
          <p className="text-xs text-slate-500">
            You'll be signed out on every device and asked to sign in again.
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
