import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { Button } from "./Button";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-2 rounded border border-danger-100 bg-sheet py-10 text-center">
      <AlertCircle className="size-5 text-danger-600" aria-hidden="true" />
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
    <div role="alert" className="flex items-start gap-2 rounded border-l-2 border-danger-500 bg-danger-50 px-3 py-2 text-sm text-danger-700">
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function InlineSuccess({ message }: { message: string }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded border-l-2 border-success-500 bg-success-50 px-3 py-2 text-sm text-success-700 animate-slide-up">
      <CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

export function InlineInfo({ message }: { message: string }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded border-l-2 border-brand-500 bg-brand-50 px-3 py-2 text-sm text-brand-800">
      <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
