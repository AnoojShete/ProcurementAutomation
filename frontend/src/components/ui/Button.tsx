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

// Ledger buttons: rectangular (4px), flat, ink-blue for the one primary
// action. Disabled is 40% opacity with no hover, so it reads as unavailable.
const variantClasses: Record<Variant, string> = {
  primary:
    "border border-accent bg-accent text-white hover:border-accent-hover hover:bg-accent-hover active:shadow-[inset_0_1px_0_rgb(0_0_0/0.25)]",
  secondary:
    "border border-rule-strong bg-sheet text-ink hover:bg-sheet-sunk active:bg-rule",
  destructive:
    "border border-danger-500 bg-sheet text-danger-600 hover:bg-danger-500 hover:text-white active:bg-danger-700",
  ghost: "border border-transparent bg-transparent text-ink-2 hover:bg-sheet-sunk hover:text-ink active:bg-rule",
};

const sizeClasses: Record<Size, string> = {
  sm: "h-7 px-2.5 text-13 gap-1.5",
  md: "h-9 px-3.5 text-sm gap-2",
  lg: "h-11 px-4 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded font-medium",
          "transition-[background-color,border-color,color,box-shadow] duration-1 ease-out",
          "disabled:pointer-events-none disabled:opacity-40 [&[aria-busy=true]]:opacity-100",
          variantClasses[variant],
          sizeClasses[size],
          className,
        )}
        {...rest}
      >
        {/* The label stays put while loading; the spinner fades in late so
            quick actions don't flicker. */}
        {loading ? (
          <span className="inline-flex animate-delayed-in" aria-hidden="true">
            <Loader2 className="size-4 shrink-0 animate-spin" />
          </span>
        ) : (
          icon
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
