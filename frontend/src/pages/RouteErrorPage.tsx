import { isRouteErrorResponse, Link, useRouteError } from "react-router-dom";
import { AlertTriangle, Compass, Lock, RefreshCw } from "lucide-react";
import type { IconType } from "@/lib/roleNav";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface Explained {
  icon: IconType;
  title: string;
  description: string;
  reload: boolean;
}

// A lazy page whose chunk vanished (the app was rebuilt while the tab was
// open) fails with one of these, depending on the browser.
const STALE_CHUNK = /dynamically imported module|Importing a module script failed|error loading dynamically imported module/i;

function explain(error: unknown): Explained {
  if (isRouteErrorResponse(error)) {
    if (error.status === 404) {
      return {
        icon: Compass,
        title: "Page not found",
        description: "The page you're looking for doesn't exist or has moved.",
        reload: false,
      };
    }
    if (error.status === 401 || error.status === 403) {
      return {
        icon: Lock,
        title: "You don't have access to this page",
        description: "Your role can't open it. Ask an admin if you think it should.",
        reload: false,
      };
    }
  }
  if (error instanceof Error && STALE_CHUNK.test(error.message)) {
    return {
      icon: RefreshCw,
      title: "A newer version of the app is available",
      description: "This page changed since you opened the app. Reload to get the latest version.",
      reload: true,
    };
  }
  return {
    icon: AlertTriangle,
    title: "Something went wrong on this page",
    description: "Your data is safe. Reload the page, or go back to the dashboard and try again.",
    reload: true,
  };
}

function technicalDetail(error: unknown): string {
  if (isRouteErrorResponse(error)) return `${error.status} ${error.statusText}`;
  if (error instanceof Error) return error.stack ?? error.message;
  return String(error);
}

/** Route `errorElement`: replaces React Router's default developer screen.
 * `inShell` keeps the sidebar and top bar around it (a page inside /app
 * crashed); without it the page fills the screen. */
export function RouteErrorPage({ inShell = false }: { inShell?: boolean }) {
  const error = useRouteError();
  const { icon: Icon, title, description, reload } = explain(error);

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-4 text-center",
        inShell ? "py-24" : "min-h-screen bg-paper",
      )}
    >
      <Icon className="mb-1 size-8 text-ink-3" strokeWidth={1.5} aria-hidden="true" />
      <h1 className="font-doc text-xl font-semibold text-ink">{title}</h1>
      <p className="max-w-md text-sm text-ink-2">{description}</p>
      <div className="mt-3 flex items-center gap-2">
        {reload && (
          <Button onClick={() => window.location.reload()} icon={<RefreshCw className="size-4" aria-hidden="true" />}>
            Reload page
          </Button>
        )}
        <Link
          to="/app"
          className="inline-flex h-9 items-center rounded border border-rule-strong bg-sheet px-3.5 text-sm font-medium text-ink hover:bg-sheet-sunk"
        >
          Go to dashboard
        </Link>
      </div>
      {import.meta.env.DEV && (
        <details className="mt-6 w-full max-w-2xl text-left">
          <summary className="cursor-pointer text-13 text-ink-3">Technical details (development only)</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded border border-rule bg-sheet p-3 font-mono text-xs text-ink-2">
            {technicalDetail(error)}
          </pre>
        </details>
      )}
    </div>
  );
}
