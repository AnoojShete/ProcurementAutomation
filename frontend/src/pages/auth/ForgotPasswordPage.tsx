import { useState } from "react";
import { Link } from "react-router-dom";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { AuthLayout, EmailField } from "@/components/auth/AuthLayout";

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSending(true);
    try {
      setSent((await authApi.forgotPassword(email)).data.message);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Couldn't send the link. Please try again.",
      );
    } finally {
      setSending(false);
    }
  };

  return (
    <AuthLayout
      title="Reset your password"
      footer={
        <Link
          to="/login"
          className="font-medium text-brand-700 hover:underline"
        >
          Back to sign in
        </Link>
      }
    >
      {sent ? (
        <InlineSuccess message={sent} />
      ) : (
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          {error && <InlineError message={error} />}
          <p className="text-sm text-slate-600">
            Enter the email you signed up with and we'll send you a link to
            choose a new password.
          </p>
          <EmailField value={email} onChange={setEmail} />
          <Button
            type="submit"
            className="w-full"
            loading={sending}
            disabled={!email}
          >
            Send reset link
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
