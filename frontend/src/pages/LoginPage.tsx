import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { authApi } from "@/api/auth";
import { DEMO_ACCOUNTS } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";

// The one-click demo accounts are for the showcase build. Set
// VITE_SHOW_DEMO_ACCOUNTS=false when building for real users.
const SHOW_DEMO_ACCOUNTS = import.meta.env.VITE_SHOW_DEMO_ACCOUNTS !== "false";

export function LoginPage() {
  const { login, status } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState<string | null>(null);

  if (status === "authenticated") return <Navigate to="/app" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setUnverified(false);
    setResent(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Unable to sign in. Please try again.",
      );
      setUnverified(e instanceof ApiError && e.code === "email_not_verified");
    } finally {
      setSubmitting(false);
    }
  };

  const pickDemoRole = (role: (typeof DEMO_ACCOUNTS)[number]) => {
    setSelectedRole(role.role);
    setEmail(role.email);
    setPassword(role.password);
    setError(null);
  };

  return (
    <div className="flex min-h-screen flex-col items-center bg-surface-subtle px-4 pt-16 pb-10 sm:pt-24">
      <div className="mb-6 flex items-center gap-2.5">
        <div className="flex size-8 items-center justify-center rounded bg-slate-900 text-xs font-bold text-white">
          PI
        </div>
        <span className="text-lg font-semibold text-slate-900">
          Procurement
        </span>
      </div>

      <div className="w-full max-w-[340px]">
        <h1 className="mb-4 text-center text-xl font-normal text-slate-900">
          Sign in to Acme Corp
        </h1>

        <form
          onSubmit={onSubmit}
          className="space-y-3 rounded-md border border-surface-border bg-white p-4"
          noValidate
        >
          {error && <InlineError message={error} />}
          {unverified &&
            (resent ? (
              <InlineSuccess message={resent} />
            ) : (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="w-full"
                onClick={async () =>
                  setResent(
                    (await authApi.resendVerification(email)).data.message,
                  )
                }
              >
                Send a new confirmation link
              </Button>
            ))}
          <div>
            <label
              htmlFor="email"
              className="mb-1 block text-sm font-medium text-slate-800"
            >
              Work email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="username"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setSelectedRole(null);
              }}
              className="field"
            />
          </div>
          <div>
            <div className="mb-1 flex items-baseline justify-between">
              <label
                htmlFor="password"
                className="block text-sm font-medium text-slate-800"
              >
                Password
              </label>
              <Link
                to="/forgot-password"
                className="text-xs font-medium text-brand-700 hover:underline"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setSelectedRole(null);
                }}
                className="field pr-9"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute inset-y-0 right-0 flex items-center px-2.5 text-slate-400 hover:text-slate-700"
              >
                {showPassword ? (
                  <EyeOff className="size-4" />
                ) : (
                  <Eye className="size-4" />
                )}
              </button>
            </div>
          </div>

          <Button
            type="submit"
            className="w-full"
            loading={submitting}
            disabled={!email || !password}
          >
            Sign in
          </Button>
        </form>

        <div className="mt-4 rounded-md border border-surface-border p-3 text-center text-sm text-slate-700">
          New here?{" "}
          <Link
            to="/signup"
            className="font-medium text-brand-700 hover:underline"
          >
            Create an account
          </Link>
        </div>

        {SHOW_DEMO_ACCOUNTS && (
          <div className="mt-4 rounded-md border border-surface-border bg-white p-4">
            <p className="mb-2 text-13 font-medium text-slate-800">
              Demo accounts
            </p>
            <div className="grid grid-cols-2 gap-1.5">
              {DEMO_ACCOUNTS.map((acct) => (
                <button
                  key={acct.role}
                  type="button"
                  onClick={() => pickDemoRole(acct)}
                  className={cn(
                    "h-8 rounded-md border px-2.5 text-left text-13 transition-colors",
                    selectedRole === acct.role
                      ? "border-brand-500 bg-brand-50 font-medium text-brand-800"
                      : "border-surface-border text-slate-700 hover:bg-surface-subtle",
                  )}
                >
                  {acct.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Fills in a seeded account. Evaluation environment only.
            </p>
          </div>
        )}

        <p className="mt-8 text-center text-xs text-slate-500">
          Access is limited to authorised Acme Corp staff. Activity is logged.
        </p>
      </div>
    </div>
  );
}
