import { ExternalLink, HeartPulse } from "lucide-react";
import { useEffect, useState } from "react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { api } from "@/api/client";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { InlineInfo } from "@/components/ui/ErrorState";
import { INFRA_LINKS, PLATFORM_SERVICES } from "@/lib/constants";

interface Quota {
  api_name: string;
  calls_used: number;
  calls_limit: number;
  remaining: number;
}

interface LiveModeStatus {
  enabled: boolean;
  quotas: Quota[];
  message?: string;
}

export function SystemHealthPage() {
  usePageHeader("System Health");
  const [liveMode, setLiveMode] = useState<LiveModeStatus | null>(null);

  useEffect(() => {
    void api.get<LiveModeStatus>("/admin/live-mode").then((response) => setLiveMode(response.data));
  }, []);

  async function toggleLiveMode() {
    if (!liveMode) return;
    if (!liveMode.enabled && !window.confirm("This will use real API quota. Continue?")) return;
    const response = await api.patch<LiveModeStatus>("/admin/live-mode", { enabled: !liveMode.enabled });
    setLiveMode(response.data);
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader title="Live Verification Mode" subtitle="Real registry calls are limited by the shared safety quota." />
        <CardBody>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <button
              type="button"
              onClick={() => void toggleLiveMode()}
              disabled={!liveMode}
              className={`rounded-md px-3 py-2 text-sm font-medium text-white ${liveMode?.enabled ? "bg-rose-600" : "bg-slate-700"}`}
            >
              {liveMode?.enabled ? "Disable Live Verification" : "Enable Live Verification"}
            </button>
            <div className="flex flex-1 flex-wrap gap-4 sm:justify-end">
              {liveMode?.quotas.map((quota) => {
                const percent = Math.min((quota.calls_used / quota.calls_limit) * 100, 100);
                return (
                  <div key={quota.api_name} className="min-w-44 text-xs text-slate-600">
                    <div className="mb-1 flex justify-between">
                      <span>{quota.api_name}</span>
                      <span>{quota.calls_used}/{quota.calls_limit}</span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200">
                      <div className={`h-full ${percent >= 80 ? "bg-rose-500" : "bg-emerald-500"}`} style={{ width: `${percent}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
          {liveMode?.message && <p className="mt-3 text-sm text-rose-600">{liveMode.message}</p>}
        </CardBody>
      </Card>
      <InlineInfo message="The API gateway only proxies business endpoints (/api/requests, /api/documents, …) — each service's own /health check isn't exposed through it, so live per-service status can't be polled from this page. Use Grafana for real-time metrics." />

      <Card>
        <CardHeader title="Kafka Consumer Lag" subtitle="Live view of unconsumed messages by group" />
        <CardBody>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <LagMonitor />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Model Routing Log" subtitle="Recent routing decisions" />
        <CardBody>
          <RoutingLog />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Live Activity Feed" subtitle="Recent notifications and events" />
        <CardBody>
          <ActivityFeed />
        </CardBody>
      </Card>

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

function LagMonitor() {
  const [lag, setLag] = useState<{group: string, lag: number}[]>([]);
  useEffect(() => {
    const fetchLag = () => api.get<{group: string, lag: number}[]>("/admin/kafka-lag").then(r => setLag(r.data)).catch(() => {});
    fetchLag();
    const interval = setInterval(fetchLag, 10000);
    return () => clearInterval(interval);
  }, []);
  
  if (lag.length === 0) return <div className="text-sm text-slate-500">No lag data available.</div>;
  return (
    <>
      {lag.map(l => (
        <div key={l.group} className="flex justify-between items-center p-3 border rounded-lg">
          <span className="font-medium text-sm text-slate-700">{l.group}</span>
          <Badge tone={l.lag > 50 ? "danger" : l.lag > 10 ? "warning" : "success"}>{l.lag} msgs</Badge>
        </div>
      ))}
    </>
  );
}

function RoutingLog() {
  const [logs, setLogs] = useState<any[]>([]);
  useEffect(() => {
    const fetchLogs = () => api.get<any[]>("/admin/model-routing-log").then(r => setLogs(r.data)).catch(() => {});
    fetchLogs();
    const interval = setInterval(fetchLogs, 10000);
    return () => clearInterval(interval);
  }, []);
  
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm text-left">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="px-4 py-2">Time</th>
            <th className="px-4 py-2">Route</th>
            <th className="px-4 py-2">Model</th>
            <th className="px-4 py-2">Fallback</th>
            <th className="px-4 py-2">Conf</th>
          </tr>
        </thead>
        <tbody className="divide-y text-slate-700">
          {logs.map((l, idx) => (
            <tr key={idx}>
              <td className="px-4 py-2 whitespace-nowrap">{new Date(l.created_at).toLocaleTimeString()}</td>
              <td className="px-4 py-2">{l.route_name}</td>
              <td className="px-4 py-2">{l.model_used}</td>
              <td className="px-4 py-2">
                {l.fallback_triggered ? <Badge tone="danger">{l.fallback_reason || "yes"}</Badge> : "-"}
              </td>
              <td className="px-4 py-2">{l.confidence?.toFixed(2)}</td>
            </tr>
          ))}
          {logs.length === 0 && <tr><td colSpan={5} className="px-4 py-2 text-slate-500">No routing events yet</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function ActivityFeed() {
  const [activities, setActivities] = useState<any[]>([]);
  useEffect(() => {
    const fetchAct = () => api.get<any[]>("/notifications/log?limit=10").then(r => setActivities(r.data)).catch(() => {});
    fetchAct();
    const interval = setInterval(fetchAct, 10000);
    return () => clearInterval(interval);
  }, []);

  if (activities.length === 0) return <div className="text-sm text-slate-500">No activity yet.</div>;
  return (
    <div className="space-y-3">
      {activities.map((a, idx) => (
        <div key={idx} className="flex justify-between items-center text-sm border-b pb-2">
          <div>
            <span className="font-medium text-slate-700">{a.template_name}</span>
            <span className="ml-2 text-slate-500">to {a.recipient} via {a.channel}</span>
          </div>
          <span className="text-xs text-slate-400">{new Date(a.created_at).toLocaleTimeString()}</span>
        </div>
      ))}
    </div>
  );
}
