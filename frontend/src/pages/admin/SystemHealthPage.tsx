import { ExternalLink, HeartPulse } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { InlineInfo } from "@/components/ui/ErrorState";
import { INFRA_LINKS, PLATFORM_SERVICES } from "@/lib/constants";

export function SystemHealthPage() {
  usePageHeader("System Health");

  return (
    <div className="flex flex-col gap-6">
      <InlineInfo message="The API gateway only proxies business endpoints (/api/requests, /api/documents, …) — each service's own /health check isn't exposed through it, so live per-service status can't be polled from this page. Use Grafana for real-time metrics." />

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-1.5">
              <HeartPulse className="size-4 text-brand-600" /> Platform Services
            </span>
          }
          subtitle="What each service owns in the procurement pipeline"
        />
        <CardBody>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {PLATFORM_SERVICES.map((svc) => (
              <div key={svc.name} className="flex items-start justify-between gap-3 rounded-lg border border-surface-border p-3.5">
                <div>
                  <p className="text-sm font-medium text-slate-800">{svc.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{svc.owns}</p>
                </div>
                <Badge tone="neutral">:{svc.port}</Badge>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Observability Tools" subtitle="Detailed metrics, workflow execution, and model tracking live in these separate tools" />
        <CardBody>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {INFRA_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-start justify-between gap-2 rounded-lg border border-surface-border p-3.5 transition-colors hover:border-brand-300"
              >
                <div>
                  <p className="text-sm font-medium text-slate-800">{link.label}</p>
                  <p className="mt-0.5 text-xs text-slate-500">{link.description}</p>
                </div>
                <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-slate-400" />
              </a>
            ))}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
