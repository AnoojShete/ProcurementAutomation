import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Boxes, Eye, EyeOff, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { DEMO_ACCOUNTS } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/cn";

export function LoginPage() {
  const { login, status } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "authenticated") return <Navigate to="/app" replace />;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to sign in. Please try again.");
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
    <div className="flex min-h-screen bg-white">
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden bg-brand-950 p-12 text-white lg:flex">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.15]"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, white 1px, transparent 1px), radial-gradient(circle at 80% 60%, white 1px, transparent 1px)",
            backgroundSize: "48px 48px, 64px 64px",
          }}
          aria-hidden="true"
        />
        <div className="relative flex items-center gap-2.5">
          <div className="flex size-9 items-center justify-center rounded-lg bg-white text-brand-800">
            <Boxes className="size-5" />
          </div>
          <span className="text-lg font-semibold">Procurement IQ</span>
        </div>

        <div className="relative max-w-md">
          <h1 className="text-3xl font-semibold leading-tight text-white">
            Agentic AI for IT procurement, end to end.
          </h1>
          <p className="mt-4 text-brand-200">
            One connected pipeline for document intelligence, approvals, vendor risk, contracts, and inventory —
            every step visible, every decision auditable.
          </p>
          <div className="mt-8 space-y-4">
            <Feature icon={Workflow} title="Automated procurement lifecycle" desc="From request to fulfillment, tracked stage by stage." />
            <Feature icon={Sparkles} title="AI-assisted intelligence" desc="Document extraction, vendor matching, and risk scoring, contextual to every decision." />
            <Feature icon={ShieldCheck} title="Governed, not autonomous" desc="Approvals, risk decisions, and payment changes always route through a human." />
          </div>
        </div>

        <p className="relative text-xs text-brand-300">© 2026 Procurement IQ — Enterprise Demo Environment</p>
      </div>

      <div className="flex w-full flex-col items-center justify-center px-6 py-12 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="flex size-9 items-center justify-center rounded-lg bg-brand-800 text-white">
              <Boxes className="size-5" />
            </div>
            <span className="text-lg font-semibold text-slate-900">Procurement IQ</span>
          </div>

          <h2 className="text-xl font-semibold text-slate-900">Sign in to your workspace</h2>
          <p className="mt-1 text-sm text-slate-500">Enter your credentials to continue.</p>

          <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
            {error && <InlineError message={error} />}
            <div>
              <label htmlFor="email" className="mb-1 block text-sm font-medium text-slate-700">
                Email
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
                className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm shadow-sm focus:border-brand-500"
                placeholder="you@company.com"
              />
            </div>
            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-medium text-slate-700">
                Password
              </label>
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
                  className="w-full rounded-lg border border-surface-border px-3 py-2 pr-10 text-sm shadow-sm focus:border-brand-500"
                  placeholder="••••••••"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
                >
                  {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                </button>
              </div>
            </div>

            <Button type="submit" size="lg" className="w-full" loading={submitting} disabled={!email || !password}>
              Sign in
            </Button>
          </form>

          <div className="mt-8 border-t border-surface-border pt-5">
            <p className="mb-2.5 text-xs font-medium uppercase tracking-wide text-slate-400">
              Demo environment — quick role switch
            </p>
            <div className="grid grid-cols-2 gap-2">
              {DEMO_ACCOUNTS.map((acct) => (
                <button
                  key={acct.role}
                  type="button"
                  onClick={() => pickDemoRole(acct)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-left text-sm font-medium transition-colors",
                    selectedRole === acct.role
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-surface-border text-slate-600 hover:border-slate-300",
                  )}
                >
                  {acct.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-slate-400">Fills in a seeded demo account — for evaluation only.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function Feature({ icon: Icon, title, desc }: { icon: typeof Workflow; title: string; desc: string }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10">
        <Icon className="size-4" />
      </div>
      <div>
        <p className="text-sm font-medium text-white">{title}</p>
        <p className="text-sm text-brand-300">{desc}</p>
      </div>
    </div>
  );
}
