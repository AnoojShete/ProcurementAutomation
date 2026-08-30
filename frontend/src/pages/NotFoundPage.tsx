import { Link } from "react-router-dom";
import { Compass } from "lucide-react";

export function NotFoundPage() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-3 bg-surface-subtle text-center">
      <Compass className="size-10 text-slate-300" />
      <h1 className="text-xl font-semibold text-slate-800">Page not found</h1>
      <p className="text-sm text-slate-500">The page you're looking for doesn't exist.</p>
      <Link to="/app" className="text-sm font-medium text-brand-700 hover:underline">
        Back to dashboard
      </Link>
    </div>
  );
}
