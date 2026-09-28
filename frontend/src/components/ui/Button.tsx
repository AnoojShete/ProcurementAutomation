import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "destructive" | "ghost";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: React.ReactNode;
}

const variantClasses: Record<Variant, string> = {
  primary:
    "border border-brand-700 bg-brand-500 text-white shadow-button hover:bg-brand-600 active:bg-brand-700 disabled:border-transparent disabled:bg-brand-200",
  secondary:
    "border border-surface-border bg-surface-subtle text-slate-800 shadow-button hover:bg-surface-muted hover:border-slate-300 active:bg-surface-border disabled:text-slate-400",
  destructive:
    "border border-surface-border bg-surface-subtle text-danger-500 shadow-button hover:border-danger-600 hover:bg-danger-500 hover:text-white disabled:text-danger-300 disabled:hover:bg-surface-subtle",
  ghost: "border border-transparent bg-transparent text-slate-600 hover:bg-surface-muted hover:text-slate-900 disabled:text-slate-300",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-7 px-2.5 text-xs gap-1.5",
  md: "h-8 px-3 text-sm gap-1.5",
  lg: "h-10 px-4 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-md font-medium transition-colors duration-100",
          "disabled:cursor-not-allowed",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...rest}
      >
        {loading ? <Loader2 className="size-4 animate-spin" /> : icon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
