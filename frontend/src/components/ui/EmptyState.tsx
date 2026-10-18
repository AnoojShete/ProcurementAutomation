import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import type { IconType } from "@/lib/roleNav";

/** Says why it's empty and what happens next, in neutral ink: an empty
 * queue is usually good news, not an error. */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
}: {
  icon?: IconType;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-4 py-10 text-center">
      <Icon className="mb-1 size-5 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="max-w-sm text-13 text-ink-3">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
