import { AlertCircle, Loader2 } from "lucide-react";
import { Button } from "./Button";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-danger-50 bg-danger-50/40 py-10 text-center">
      <AlertCircle className="size-6 text-danger-500" />
      <p className="max-w-sm text-sm font-medium text-danger-700">{message}</p>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-1">
          Try again
        </Button>
      )}
    </div>
  );
}

export function InlineError({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-danger-50 bg-danger-50 px-3 py-2 text-sm text-danger-700">
      <AlertCircle className="mt-0.5 size-4 shrink-0" />
      <span>{message}</span>
    </div>
  );
}

export function InlineSuccess({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-success-50 bg-success-50 px-3 py-2 text-sm text-success-700">
      <span>{message}</span>
    </div>
  );
}

export function InlineInfo({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-brand-100 bg-brand-50 px-3 py-2 text-sm text-brand-700">
      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" />
      <span>{message}</span>
    </div>
  );
}
