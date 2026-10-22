import { useEffect, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { authApi } from "@/api/auth";
import { DEMO_ACCOUNTS } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";
import { Wordmark } from "@/components/auth/AuthLayout";

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
  const [demoAccounts, setDemoAccounts] = useState(DEMO_ACCOUNTS);

  useEffect(() => {
    if (!SHOW_DEMO_ACCOUNTS) return;
    authApi
      .getDemoAccounts()
      .then((res) => {
        if (res.data && res.data.length > 0) {
          setDemoAccounts((prev) =>
            prev.map((acct) => {
              const match = res.data.find(
                (d) => d.role.toLowerCase() === acct.role.toLowerCase(),
              );
              if (!match) return acct;
              const roleName = acct.role.charAt(0).toUpperCase() + acct.role.slice(1);
              const label = match.display_name
                ? `${match.display_name} · ${roleName}`
                : acct.label;
              return {
                ...acct,
                email: match.email,
                label,
              };
            }),
          );
        }
      })
      .catch(() => {
        // Fallback to static DEMO_ACCOUNTS if endpoint is unavailable
      });
  }, []);

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

  const pickDemoRole = (role: (typeof demoAccounts)[number]) => {
    setSelectedRole(role.role);
    setEmail(role.email);
    setPassword(role.password);
    setError(null);
  };

  return (
    <div className="flex min-h-screen flex-col items-center bg-paper px-4 pb-10 pt-12 sm:pt-20">
      <div className="w-full max-w-[400px]">
        <div className="mb-8">
          <Wordmark />
        </div>

        <div className="rounded border border-rule bg-sheet px-5 py-6 sm:px-7">
          <h1 className="mb-5 text-title font-semibold text-ink">Sign in to Acme Corp</h1>
          <form
            onSubmit={onSubmit}
            className="space-y-4"
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
                className="mb-1.5 block text-sm font-medium text-ink"
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
              <div className="mb-1.5 flex items-baseline justify-between">
                <label
                  htmlFor="password"
                  className="block text-sm font-medium text-ink"
                >
                  Password
                </label>
                <Link
                  to="/forgot-password"
                  className="text-13 font-medium text-accent hover:underline"
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
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-ink-3 hover:text-ink"
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
              size="lg"
              className="w-full"
              loading={submitting}
              disabled={!email || !password}
            >
              Sign in
            </Button>
          </form>
          <p className="mt-5 border-t border-rule pt-4 text-center text-sm text-ink-2">
            New here?{" "}
            <Link to="/signup" className="font-medium text-accent hover:underline">
              Create an account
            </Link>
          </p>
        </div>

        {SHOW_DEMO_ACCOUNTS && (
          <section aria-labelledby="eval-title" className="mt-6 rounded border border-dashed border-rule-strong bg-sheet-sunk/60 p-4">
            <div className="flex items-baseline justify-between gap-3">
              <h2 id="eval-title" className="text-sm font-semibold text-ink">
                Evaluation accounts
              </h2>
              <span className="text-caption text-ink-3">Demo environment only</span>
            </div>
            <p className="mt-1 text-13 text-ink-2">Pick a role to fill in a seeded account, then sign in.</p>
            <ul className="mt-3 divide-y divide-rule overflow-hidden rounded border border-rule bg-sheet">
              {demoAccounts.map((acct) => {
                const selected = selectedRole === acct.role;
                return (
                  <li key={acct.role}>
                    <button
                      type="button"
                      onClick={() => pickDemoRole(acct)}
                      aria-pressed={selected}
                      className={cn(
                        "flex min-h-11 w-full items-center justify-between gap-3 px-3 py-2 text-left transition-colors duration-1 focus-visible:ring-inset focus-visible:ring-offset-0",
                        selected ? "bg-accent-tint shadow-[inset_2px_0_0_rgb(var(--accent))]" : "hover:bg-sheet-sunk",
                      )}
                    >
                      <span className={cn("text-sm", selected ? "font-medium text-accent" : "text-ink")}>{acct.label}</span>
                      <span className="truncate font-mono text-caption text-ink-3">{acct.email}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        <p className="mt-8 text-center text-caption text-ink-3">
          Access is limited to authorised Acme Corp staff. Activity is logged.
        </p>
      </div>
    </div>
  );
}
