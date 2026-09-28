import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { authApi, takeTokenFromUrl } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/Button";
import {
  InlineError,
  InlineInfo,
  InlineSuccess,
} from "@/components/ui/ErrorState";
import { AuthLayout, EmailField } from "@/components/auth/AuthLayout";

/** Opened from the confirmation email (/verify-email#token=…). Without a
 * token it offers to send a new link. */
export function VerifyEmailPage() {
  const token = useRef<string | null>(takeTokenFromUrl());
  const [state, setState] = useState<
    "checking" | "verified" | "failed" | "idle"
  >(token.current ? "checking" : "idle");
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (!token.current) return;
    const t = token.current;
    token.current = null; // React StrictMode runs effects twice; the link works once
    authApi
      .verifyEmail(t)
      .then(() => setState("verified"))
      .catch((e) => {
        setError(
          e instanceof ApiError ? e.message : "Couldn't confirm your email.",
        );
        setState("failed");
      });
  }, []);

  const resend = async (e: React.FormEvent) => {
    e.preventDefault();
    setSending(true);
    try {
      setSent((await authApi.resendVerification(email)).data.message);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't send the link.");
    } finally {
      setSending(false);
    }
  };

  if (state === "checking")
    return (
      <AuthLayout title="Confirming your email">
        <InlineInfo message="One moment…" />
      </AuthLayout>
    );

  if (state === "verified")
    return (
      <AuthLayout title="Email confirmed">
        <InlineSuccess message="Your email address is confirmed. You can sign in now." />
        <Link to="/login" className="block">
          <Button className="w-full">Sign in</Button>
        </Link>
      </AuthLayout>
    );

  return (
    <AuthLayout
      title="Confirm your email"
      footer={
        <Link
          to="/login"
          className="font-medium text-brand-700 hover:underline"
        >
          Back to sign in
        </Link>
      }
    >
      {error && <InlineError message={error} />}
      {sent ? (
        <InlineSuccess message={sent} />
      ) : (
        <form onSubmit={resend} className="space-y-3" noValidate>
          <p className="text-sm text-slate-600">
            Enter your email and we'll send a new confirmation link.
          </p>
          <EmailField value={email} onChange={setEmail} />
          <Button
            type="submit"
            className="w-full"
            loading={sending}
            disabled={!email}
          >
            Send new link
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
