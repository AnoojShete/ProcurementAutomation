import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff } from "lucide-react";

/** "Procurement" over the accountant's double rule: the product's mark. */
export function Wordmark() {
  return (
    <div className="leading-tight">
      <p className="rule-double inline-block pb-0.5 text-lg font-semibold tracking-[-0.01em] text-ink">Procurement</p>
      <p className="mt-1 text-13 text-ink-3">Acme Corp</p>
    </div>
  );
}

/** Frame for the signed-out pages (sign in, sign up, password reset…). */
export function AuthLayout({
  title,
  children,
  footer,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center bg-paper px-4 pb-10 pt-16 sm:pt-24">
      <Link
        to="/login"
        aria-label="Back to sign in"
        title="Back to sign in"
        className="absolute left-4 top-4 rounded p-2 text-ink-2 hover:bg-sheet-sunk hover:text-ink"
      >
        <ArrowLeft className="size-5" strokeWidth={1.75} />
      </Link>
      <div className="w-full max-w-[400px]">
        <div className="mb-8">
          <Wordmark />
        </div>
        <div className="rounded border border-rule bg-sheet px-5 py-6 sm:px-7">
          <h1 className="mb-5 text-title font-semibold text-ink">{title}</h1>
          <div className="space-y-4">{children}</div>
        </div>
        {footer && <div className="mt-4 text-center text-sm text-ink-2">{footer}</div>}
      </div>
    </div>
  );
}

export const PASSWORD_HINT =
  "At least 12 characters. A few unrelated words work well.";

export function PasswordField({
  id,
  label,
  value,
  onChange,
  autoComplete,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: "current-password" | "new-password";
  hint?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm font-medium text-ink"
      >
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={show ? "text" : "password"}
          required
          autoComplete={autoComplete}
          minLength={autoComplete === "new-password" ? 12 : undefined}
          maxLength={128}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="field pr-9"
        />
        <button
          type="button"
          onClick={() => setShow((v) => !v)}
          aria-label={show ? "Hide password" : "Show password"}
          className="absolute inset-y-0 right-0 flex items-center px-3 text-ink-3 hover:text-ink"
        >
          {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      {hint && <p className="mt-1.5 text-caption text-ink-3">{hint}</p>}
    </div>
  );
}

export function EmailField({
  value,
  onChange,
  label = "Email",
}: {
  value: string;
  onChange: (v: string) => void;
  label?: string;
}) {
  return (
    <div>
      <label
        htmlFor="email"
        className="mb-1.5 block text-sm font-medium text-ink"
      >
        {label}
      </label>
      <input
        id="email"
        type="email"
        required
        autoComplete="username"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="field"
      />
    </div>
  );
}
