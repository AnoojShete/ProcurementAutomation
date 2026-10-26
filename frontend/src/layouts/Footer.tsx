import { Link } from "react-router-dom";
import { BookOpen, Code2, Github } from "lucide-react";
import type { IconType } from "@/lib/roleNav";

const LINKS: { label: string; to: string; icon: IconType; external?: boolean }[] = [
  { label: "System Developers", to: "/app/developers", icon: Code2 },
  { label: "Documentation", to: "https://anoojshete.github.io/ProcurementAutomation/", icon: BookOpen, external: true },
  { label: "Source code", to: "https://github.com/AnoojShete/ProcurementAutomation", icon: Github, external: true },
];

const linkClass = "inline-flex items-center gap-1.5 rounded hover:text-ink hover:underline";

/** The line under every page: who built it and where the docs and code live. */
export function Footer() {
  return (
    <footer className="mt-12 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-t border-rule pt-4 text-caption text-ink-3">
      <p>Agentic AI Procurement Solution · Fr. C. Rodrigues Institute of Technology, Vashi · 2026</p>
      <nav aria-label="Footer" className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {LINKS.map(({ label, to, icon: Icon, external }) => {
          const content = (
            <>
              <Icon className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden="true" />
              {label}
            </>
          );
          return external ? (
            <a key={to} href={to} target="_blank" rel="noopener noreferrer" className={linkClass}>
              {content}
            </a>
          ) : (
            <Link key={to} to={to} className={linkClass}>
              {content}
            </Link>
          );
        })}
      </nav>
    </footer>
  );
}
