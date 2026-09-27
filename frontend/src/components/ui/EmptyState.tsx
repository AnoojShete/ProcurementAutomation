import type { ReactNode } from "react";
import { Inbox } from "lucide-react";
import type { IconType } from "@/lib/roleNav";

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
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg py-12 text-center">
      <Icon className="mb-1 size-6 text-slate-400" strokeWidth={1.5} />
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      {description && <p className="max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
