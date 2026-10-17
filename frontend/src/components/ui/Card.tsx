import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

/** A white sheet on the paper background. Use it around things you act on
 * (forms, action panels) and dense tables; plain read-only content belongs
 * in a `Section` instead. Flat: a hairline, never a shadow. */
export function Card({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("rounded border border-rule bg-sheet", className)} {...rest}>
      {children}
    </div>
  );
}

/** Sheet header: section heading with a hairline under it. `action` sits on
 * the right (buttons, links, filters). */
export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-rule px-4 py-3 sm:px-5", className)}>
      <div className="min-w-0">
        <h3 className="text-heading font-semibold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-13 text-ink-3">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function CardBody({ className, children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn("p-4 sm:p-5", className)} {...rest}>
      {children}
    </div>
  );
}

/** A ruled section: heading, hairline, then content straight on the page.
 * The Ledger alternative to a box around everything. */
export function Section({
  title,
  subtitle,
  action,
  className,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={cn("min-w-0", className)}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-1 border-b border-ink/70 pb-2">
        <div className="min-w-0">
          <h2 className="text-heading font-semibold text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-13 text-ink-3">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
