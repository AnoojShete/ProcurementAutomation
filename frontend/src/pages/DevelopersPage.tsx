import { Github, Linkedin, Mail } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Section } from "@/components/ui/Card";
import { initials } from "@/lib/format";
import { DEVELOPERS } from "@/lib/developers";

/** The four students who built the system, with their contact links.
 * Same details as the report, the paper and the docs site's Team page. */
export function DevelopersPage() {
  usePageHeader("System developers");

  return (
    <div className="space-y-6">
      <Section
        title="System developers"
        subtitle="Department of Computer Engineering, Fr. C. Rodrigues Institute of Technology, Vashi"
      >
        <ul className="grid gap-4 sm:grid-cols-2">
          {DEVELOPERS.map((dev) => (
            <li key={dev.email} className="rounded border border-rule bg-sheet p-4 sm:p-5">
              <div className="flex items-start gap-3">
                <div
                  className="flex size-10 shrink-0 items-center justify-center rounded-full bg-paper text-13 font-semibold text-ink-2 ring-1 ring-rule-mid"
                  aria-hidden="true"
                >
                  {/* First name and surname: "AM", not "AD" from the middle name. */}
                  {initials(`${dev.name.split(" ")[0]} ${dev.name.split(" ").slice(-1)[0]}`)}
                </div>
                <div className="min-w-0">
                  <h3 className="text-heading font-semibold text-ink">{dev.name}</h3>
                  <p className="mt-0.5 text-13 text-ink-3">{dev.work}</p>
                </div>
              </div>
              <ul className="mt-4 space-y-1.5 text-13">
                <ContactLink icon={Mail} href={`mailto:${dev.email}`} label={dev.email} title="Email" />
                <ContactLink
                  icon={Linkedin}
                  href={`https://www.linkedin.com/in/${dev.linkedin}`}
                  label={`linkedin.com/in/${dev.linkedin}`}
                  title="LinkedIn"
                />
                <ContactLink
                  icon={Github}
                  href={`https://github.com/${dev.github}`}
                  label={`github.com/${dev.github}`}
                  title="GitHub"
                />
              </ul>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function ContactLink({ icon: Icon, href, label, title }: { icon: typeof Mail; href: string; label: string; title: string }) {
  const external = href.startsWith("http");
  return (
    <li>
      <a
        href={href}
        title={title}
        {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
        className="inline-flex max-w-full items-center gap-2 rounded text-ink-2 hover:text-accent hover:underline"
      >
        <Icon className="size-4 shrink-0 text-ink-3" strokeWidth={1.75} aria-label={title} />
        <span className="truncate">{label}</span>
      </a>
    </li>
  );
}
