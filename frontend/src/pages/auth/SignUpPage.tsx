import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import {
  AuthLayout,
  EmailField,
  PASSWORD_HINT,
  PasswordField,
} from "@/components/auth/AuthLayout";

export function SignUpPage() {
  const { status } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (status === "authenticated") return <Navigate to="/app" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("The two passwords don't match.");
    setSubmitting(true);
    try {
      const res = await authApi.register(email, password);
      setDone(res.data.message);
      setPassword("");
      setConfirm("");
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Couldn't create the account. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthLayout
      title="Create your account"
      footer={
        <>
          Already have an account?{" "}
          <Link
            to="/login"
            className="font-medium text-brand-700 hover:underline"
          >
            Sign in
          </Link>
        </>
      }
    >
      {done ? (
        <>
          <InlineSuccess message={done} />
          <p className="text-sm text-slate-600">
            Didn't get it? Check your spam folder, or{" "}
            <Link
              to="/verify-email"
              className="font-medium text-brand-700 hover:underline"
            >
              send a new link
            </Link>
            .
          </p>
        </>
      ) : (
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          {error && <InlineError message={error} />}
          <EmailField value={email} onChange={setEmail} label="Work email" />
          <PasswordField
            id="password"
            label="Password"
            value={password}
            onChange={setPassword}
            autoComplete="new-password"
            hint={PASSWORD_HINT}
          />
          <PasswordField
            id="confirm"
            label="Confirm password"
            value={confirm}
            onChange={setConfirm}
            autoComplete="new-password"
          />
          <Button
            type="submit"
            className="w-full"
            loading={submitting}
            disabled={!email || !password || !confirm}
          >
            Create account
          </Button>
          <p className="text-xs text-slate-500">
            New accounts start as requesters. An administrator can change your
            role.
          </p>
        </form>
      )}
    </AuthLayout>
  );
}
