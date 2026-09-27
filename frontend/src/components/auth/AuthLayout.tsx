import { useState, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";

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
          {title}
        </h1>
        <div className="space-y-3 rounded-md border border-surface-border bg-white p-4">
          {children}
        </div>
        {footer && (
          <div className="mt-4 rounded-md border border-surface-border p-3 text-center text-sm text-slate-700">
            {footer}
          </div>
        )}
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
        className="mb-1 block text-sm font-medium text-slate-800"
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
          className="absolute inset-y-0 right-0 flex items-center px-2.5 text-slate-400 hover:text-slate-700"
        >
          {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </button>
      </div>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
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
        className="mb-1 block text-sm font-medium text-slate-800"
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
