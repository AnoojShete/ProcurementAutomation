import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Database, ExternalLink, FolderInput, Pause, PenLine, Play, Radio } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useDebounce } from "@/hooks/useDebounce";
import { ApiError } from "@/api/client";
import type { ApiEnvelope } from "@/types/api";
import {
  controlPanelApi,
  type DropStage,
  type EsignStatus,
  type InboxStatus,
  type KafkaEvent,
  type StorageStatus,
  type EventFilters,
} from "@/api/controlPanel";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { InlineError } from "@/components/ui/ErrorState";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand";

/** Fetches now and every `ms`, keeping the last good data while a poll fails. */
function usePoll<T>(fetcher: () => Promise<ApiEnvelope<T>>, ms: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef(fetcher);
  ref.current = fetcher;
  useEffect(() => {
    let cancelled = false;
    const run = () =>
      ref
        .current()
        .then((r) => {
          if (cancelled) return;
          setData(r.data);
          setError(null);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof ApiError ? e.message : "Couldn't reach the service.");
        });
    void run();
    const id = setInterval(run, ms);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ms]);
  return { data, error };
}

function formatBytes(n: number | undefined) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), units.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${units[i]}`;
}

function StatusDot({ tone }: { tone: Tone }) {
  const color = { success: "bg-success-500", warning: "bg-warning-500", danger: "bg-danger-500", neutral: "bg-slate-400", brand: "bg-brand-500" }[tone];
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", color)} />;
}

function ConnectionCard({
  icon: Icon,
  title,
  tone,
  state,
  children,
  action,
}: {
  icon: typeof Database;
  title: string;
  tone: Tone;
  state: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <Card className="flex flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-surface-border px-4 py-2.5">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <Icon className="size-4 text-slate-500" strokeWidth={1.75} /> {title}
        </span>
        <span className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
          <StatusDot tone={tone} /> {state}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-4 text-xs text-slate-600">{children}</div>
      {action && <div className="border-t border-surface-border px-4 py-2 text-xs">{action}</div>}
    </Card>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 truncate text-right font-medium text-slate-800">{children}</span>
    </div>
  );
}

const FLOW = ["Drop folder", "Kafka", "Document pipeline", "Purchase request", "Approval", "Contract", "E-signature"];

const STAGE_TONE: Record<DropStage, Tone> = {
  processing: "brand",
  approval: "warning",
  review: "warning",
  contract: "warning",
  signature: "brand",
  signed: "success",
  failed: "danger",
  rejected: "danger",
  stopped: "neutral",
};

/** The drop-folder automation on one page: the connections it runs on, where
 * each dropped file is, and the Kafka events as they happen. Read-only —
 * each row links to the item's own page for any action. */
export function ControlPanelPage() {
  usePageHeader("Control Panel");
  const inbox = usePoll(() => controlPanelApi.inbox(), 4000);
  const storage = usePoll(() => controlPanelApi.storage(), 15000);
  const esign = usePoll(() => controlPanelApi.esign(), 15000);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-slate-600">
        Put a vendor quote (PDF, PNG or JPEG) in the <code className="rounded bg-surface-muted px-1">./inbox</code> folder.
        It is picked up within seconds and runs through every agent on its own; the contract goes out for signature once.
      </p>

      <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-600">
        {FLOW.map((step, i) => (
          <span key={step} className="flex items-center gap-1.5">
            <span className="rounded border border-surface-border bg-white px-2 py-1 font-medium text-slate-700">{step}</span>
            {i < FLOW.length - 1 && <ArrowRight className="size-3 text-slate-400" />}
          </span>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <DropFolderCard inbox={inbox.data} error={inbox.error} />
        <KafkaCard />
        <MinioCard storage={storage.data} error={storage.error} />
        <DocusignCard esign={esign.data} error={esign.error} />
      </div>

      <DropsCard inbox={inbox.data} error={inbox.error} />

      <EventLogCard />

      <FailedEventsCard />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <MinioObjectsCard storage={storage.data} />
        {esign.data?.docusign.configured && <EnvelopesCard esign={esign.data} />}
      </div>
    </div>
  );
}

function DropFolderCard({ inbox, error }: { inbox: InboxStatus | null; error: string | null }) {
  if (!inbox) return error ? <InlineError message={`Drop folder: ${error}`} /> : <Skeleton className="h-40" />;
  const ok = inbox.enabled && inbox.folder.mounted;
  return (
    <ConnectionCard icon={FolderInput} title="Drop folder" tone={ok ? "success" : "danger"} state={ok ? "Watching" : "Not mounted"}>
      <Row label="Folder">{inbox.host_path}</Row>
      <Row label="Checked every">{inbox.poll_seconds}s</Row>
      <Row label="Waiting">{inbox.folder.waiting.length}</Row>
      <Row label="Rejected">{inbox.folder.failed.length}</Row>
      {inbox.folder.failed.slice(0, 2).map((f) => (
        <p key={f.name} className="truncate text-danger-600" title={f.reason}>
          {f.name}: {f.reason}
        </p>
      ))}
    </ConnectionCard>
  );
}

function KafkaCard() {
  const { data, error } = usePoll(() => controlPanelApi.events(Number.MAX_SAFE_INTEGER), 5000);
  if (!data) return error ? <InlineError message={`Kafka: ${error}`} /> : <Skeleton className="h-40" />;
  const s = data.status;
  return (
    <ConnectionCard icon={Radio} title="Kafka (Redpanda)" tone={s.connected ? "success" : "danger"} state={s.connected ? "Connected" : "Disconnected"}>
      <Row label="Login">event-monitor (read-only)</Row>
      <Row label="Topics tailed">{s.topics?.length ?? 0}</Row>
      <Row label="Events seen">{data.latest_seq}</Row>
      {s.error && <p className="text-danger-600">{s.error}</p>}
    </ConnectionCard>
  );
}

function MinioCard({ storage, error }: { storage: StorageStatus | null; error: string | null }) {
  if (!storage) return error ? <InlineError message={`MinIO: ${error}`} /> : <Skeleton className="h-40" />;
  return (
    <ConnectionCard
      icon={Database}
      title="MinIO"
      tone={storage.connected ? "success" : "danger"}
      state={storage.connected ? "Connected" : "Unreachable"}
      action={
        <a href={storage.console_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-700 hover:underline">
          Open MinIO console <ExternalLink className="size-3" />
        </a>
      }
    >
      <Row label="Endpoint">{storage.endpoint}</Row>
      <Row label="Bucket">{storage.bucket}</Row>
      {storage.connected ? (
        <>
          <Row label="Objects">
            {storage.object_count}
            {storage.count_capped ? "+" : ""}
          </Row>
          <Row label="Stored">{formatBytes(storage.total_bytes)}</Row>
        </>
      ) : (
        <p className="text-danger-600">{storage.error}</p>
      )}
    </ConnectionCard>
  );
}

function DocusignCard({ esign, error }: { esign: EsignStatus | null; error: string | null }) {
  if (!esign) return error ? <InlineError message={`E-signature: ${error}`} /> : <Skeleton className="h-40" />;
  const ds = esign.docusign;
  const [tone, state]: [Tone, string] = !ds.configured
    ? ["success", "Built-in"]
    : ds.connected
      ? ["success", `Connected (${ds.environment})`]
      : ds.consent_url
        ? ["warning", "Needs consent"]
        : ["danger", "Login failed"];
  return (
    <ConnectionCard
      icon={PenLine}
      title="E-signature"
      tone={tone}
      state={state}
      action={
        ds.consent_url ? (
          <a href={ds.consent_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
            Grant consent (once) <ExternalLink className="size-3" />
          </a>
        ) : !ds.configured ? (
          <span className="text-slate-500">Signed in the app: typed or drawn signature, consent and a SHA-256 seal.</span>
        ) : undefined
      }
    >
      <Row label="Auto-send">{esign.auto_send.enabled ? `on, via ${esign.auto_send.provider}` : "off"}</Row>
      <Row label="Signer">
        {esign.auto_send.signer_email ||
          (esign.auto_send.provider === "builtin" ? "an authorised signatory, in the app" : "vendor contact email")}
      </Row>
      {ds.configured && <Row label="Account">{ds.account_id}</Row>}
      {ds.configured && <Row label="Completion">{ds.connect_webhook ? "Connect webhook + polling" : `polled every ${ds.poll_seconds}s`}</Row>}
      {ds.error && !ds.consent_url && <p className="text-danger-600">{ds.error}</p>}
    </ConnectionCard>
  );
}

function DropsCard({ inbox, error }: { inbox: InboxStatus | null; error: string | null }) {
  return (
    <Card>
      <CardHeader title="Dropped files" subtitle="Where each file from the drop folder is now. Refreshes every few seconds." />
      {!inbox ? (
        <CardBody>{error ? <InlineError message={error} /> : <Skeleton className="h-24" />}</CardBody>
      ) : inbox.drops.length === 0 && inbox.folder.waiting.length === 0 ? (
        <CardBody>
          <p className="text-sm text-slate-500">Nothing dropped yet. Copy a quote PDF into ./inbox to start.</p>
        </CardBody>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-left text-13">
            <thead className="bg-surface-subtle text-xs text-slate-500">
              <tr>
                <th className="px-4 py-2 font-medium">File</th>
                <th className="px-4 py-2 font-medium">Dropped</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Open</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-surface-border">
              {inbox.folder.waiting.map((name) => (
                <tr key={`waiting-${name}`}>
                  <td className="px-4 py-2 font-medium text-slate-800">{name}</td>
                  <td className="px-4 py-2 text-slate-500">just now</td>
                  <td className="px-4 py-2">
                    <Badge tone="brand">Picking up</Badge>
                  </td>
                  <td className="px-4 py-2" />
                </tr>
              ))}
              {inbox.drops.map((d) => (
                <tr key={d.document_id}>
                  <td className="max-w-64 truncate px-4 py-2 font-medium text-slate-800" title={d.original_filename ?? ""}>
                    {d.original_filename ?? d.document_id.slice(0, 8)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-500">{formatRelativeTime(d.uploaded_at)}</td>
                  <td className="px-4 py-2">
                    <span className="flex flex-wrap items-center gap-2">
                      <Badge tone={STAGE_TONE[d.stage]}>{d.stage}</Badge>
                      <span className="text-slate-600">{d.stage_label}</span>
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-xs">
                    <span className="flex gap-3">
                      <Link to={`/app/documents/${d.document_id}`} className="text-brand-700 hover:underline">Document</Link>
                      {d.request_id && <Link to={`/app/requests/${d.request_id}`} className="text-brand-700 hover:underline">Request</Link>}
                      {d.contract_id && <Link to={`/app/contracts/${d.contract_id}`} className="text-brand-700 hover:underline">Contract</Link>}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// Topic colours on the dark log background, by the topic's first word.
const TOPIC_COLOR: Record<string, string> = {
  document: "text-sky-300",
  vendor: "text-violet-300",
  approval: "text-amber-300",
  contract: "text-emerald-300",
  invoice: "text-rose-300",
};

function topicColor(topic: string) {
  return TOPIC_COLOR[topic.split(".")[0]] ?? "text-slate-400";
}

const MAX_EVENTS = 500;

const WINDOWS: [string, number | undefined][] = [["Any time", undefined], ["Last hour", 1], ["Last 24 h", 24], ["Last 7 days", 168]];

function EventLogCard() {
  const [events, setEvents] = useState<KafkaEvent[]>([]);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [topics, setTopics] = useState<string[]>([]);
  const [paused, setPaused] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  // Filters run on the server: the log is stored (event_log), not just what this tab has seen.
  const [topic, setTopic] = useState("");
  const [sinceHours, setSinceHours] = useState<number | undefined>(undefined);
  const [correlation, setCorrelation] = useState("");
  const [search, setSearch] = useState("");
  const query = useDebounce(search, 400);
  const lastSeq = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    let cancelled = false;
    lastSeq.current = 0;
    setEvents([]);
    const filters: EventFilters = { topic, since_hours: sinceHours, correlation_id: correlation.trim(), q: query.trim() };
    const poll = async () => {
      if (pausedRef.current) return;
      try {
        const { data } = await controlPanelApi.events(lastSeq.current, filters);
        if (cancelled) return;
        setConnected(data.status.connected);
        if (data.status.topics?.length) setTopics(data.status.topics);
        if (data.events.length) {
          lastSeq.current = data.events[data.events.length - 1].seq;
          setEvents((prev) => [...data.events.slice().reverse(), ...prev].slice(0, MAX_EVENTS));
        }
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    void poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [topic, sinceHours, correlation, query]);

  const field = "h-7 rounded border border-surface-border bg-white px-2 text-xs text-slate-700";
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Kafka log
            {connected !== null && <StatusDot tone={connected ? "success" : "danger"} />}
          </span>
        }
        subtitle="Every event on every topic, newest first — kept across restarts. Click a row for its fields."
        action={
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            className="inline-flex h-7 items-center gap-1 rounded border border-surface-border px-2 text-xs text-slate-700 hover:bg-surface-subtle"
          >
            {paused ? <Play className="size-3" /> : <Pause className="size-3" />}
            {paused ? "Resume" : "Pause"}
          </button>
        }
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-surface-border px-4 py-2">
        <select value={topic} onChange={(e) => setTopic(e.target.value)} className={field} aria-label="Filter by topic">
          <option value="">All topics</option>
          {topics.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <select
          value={sinceHours ?? ""}
          onChange={(e) => setSinceHours(e.target.value ? Number(e.target.value) : undefined)}
          className={field}
          aria-label="Time window"
        >
          {WINDOWS.map(([label, h]) => <option key={label} value={h ?? ""}>{label}</option>)}
        </select>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search text" className={cn(field, "w-40")} aria-label="Search" />
        <input
          value={correlation}
          onChange={(e) => setCorrelation(e.target.value)}
          placeholder="Correlation id"
          className={cn(field, "w-72 font-mono")}
          aria-label="Correlation id"
        />
        {(topic || sinceHours || correlation || search) && (
          <button
            type="button"
            onClick={() => { setTopic(""); setSinceHours(undefined); setCorrelation(""); setSearch(""); }}
            className="text-xs font-medium text-brand-700 hover:underline"
          >
            Clear
          </button>
        )}
      </div>
      <div className="max-h-[28rem] overflow-y-auto bg-slate-950 px-3 py-2 font-mono text-xs leading-relaxed scrollbar-thin">
        {events.length === 0 && <p className="py-6 text-center text-slate-500">No events match.</p>}
        {events.map((e) => (
          <div key={e.seq} className="border-b border-white/5 last:border-0">
            <button
              type="button"
              onClick={() => setExpanded(expanded === e.seq ? null : e.seq)}
              className="flex w-full gap-3 py-1 text-left hover:bg-white/5"
            >
              <span className="shrink-0 text-slate-500">
                {e.timestamp ? new Date(e.timestamp).toLocaleString([], { dateStyle: "short", timeStyle: "medium" }) : "--"}
              </span>
              <span className={cn("w-44 shrink-0 truncate font-semibold", topicColor(e.topic))}>{e.topic}</span>
              <span className="min-w-0 flex-1 text-slate-200">{e.message}</span>
              <span className="hidden shrink-0 text-slate-500 md:inline">{e.source_service}</span>
            </button>
            {expanded === e.seq && (
              <div className="mb-1.5 ml-[4.5rem] grid gap-x-4 rounded bg-white/5 px-3 py-2 text-slate-300 sm:grid-cols-2">
                <span className="text-slate-500">partition {e.partition} · offset {e.offset}</span>
                <span className="truncate text-slate-500">
                  correlation{" "}
                  {e.correlation_id ? (
                    <button type="button" className="text-sky-300 hover:underline" onClick={() => setCorrelation(e.correlation_id!)}>
                      {e.correlation_id}
                    </button>
                  ) : "-"}
                </span>
                {Object.entries(e.fields).map(([k, v]) => (
                  <span key={k} className="truncate">
                    <span className="text-slate-500">{k}</span>={typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Events a consumer gave up on after its retries (event_dlq). Replay /
 * discard stay on the Controls page; this shows what failed and why. */
function FailedEventsCard() {
  const { data, error } = usePoll(() => controlPanelApi.failedEvents(), 10000);
  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Failed events
            <StatusDot tone={data && data.length > 0 ? "danger" : "success"} />
          </span>
        }
        subtitle="Events a service couldn't process after retrying (dead-letter queue)."
      />
      {error && <div className="p-4"><InlineError message={error} /></div>}
      {data && data.length === 0 && <p className="p-4 text-sm text-slate-500">None — every event was processed.</p>}
      {data && data.length > 0 && (
        <div className="divide-y divide-surface-border">
          {data.map((f) => (
            <div key={f.id} className="flex flex-col gap-0.5 px-4 py-2.5 text-13">
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="font-mono text-xs font-semibold text-danger-600">{f.topic}</span>
                <span className="text-slate-700">{f.message}</span>
                <span className="ml-auto text-xs text-slate-500">
                  {f.consumer} · {f.attempts} attempts · {new Date(f.failed_at).toLocaleString()}
                </span>
              </div>
              <span className="truncate font-mono text-xs text-slate-500" title={f.error}>{f.error}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function MinioObjectsCard({ storage }: { storage: StorageStatus | null }) {
  return (
    <Card>
      <CardHeader title="Latest files in MinIO" subtitle={storage ? `Bucket ${storage.bucket}` : undefined} />
      <CardBody className="p-0">
        {!storage?.recent?.length ? (
          <p className="p-4 text-sm text-slate-500">{storage?.connected === false ? "MinIO is unreachable." : "No files stored yet."}</p>
        ) : (
          <ul className="divide-y divide-surface-border text-13">
            {storage.recent.map((o) => (
              <li key={o.key} className="flex items-center justify-between gap-3 px-4 py-2">
                <span className="min-w-0 truncate font-mono text-xs text-slate-700" title={o.key}>{o.key}</span>
                <span className="shrink-0 text-xs text-slate-500">
                  {formatBytes(o.size)} · {formatRelativeTime(o.last_modified)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function EnvelopesCard({ esign }: { esign: EsignStatus | null }) {
  return (
    <Card>
      <CardHeader title="DocuSign envelopes" subtitle="Contracts sent through DocuSign, newest first" />
      <CardBody className="p-0">
        {!esign?.envelopes.length ? (
          <p className="p-4 text-sm text-slate-500">No contracts sent through DocuSign yet.</p>
        ) : (
          <ul className="divide-y divide-surface-border text-13">
            {esign.envelopes.map((env) => (
              <li key={env.contract_id} className="flex items-center justify-between gap-3 px-4 py-2">
                <div className="min-w-0">
                  <Link to={`/app/contracts/${env.contract_id}`} className="font-medium text-brand-700 hover:underline">
                    Contract {env.contract_id.slice(0, 8)}
                  </Link>
                  <p className="truncate text-xs text-slate-500">
                    to {env.signer_email ?? "?"} · {formatRelativeTime(env.sent_at)}
                    {env.automatic ? " · automatic" : ""}
                    {env.live ? "" : " · simulated"}
                  </p>
                </div>
                <Badge tone={env.status === "signed" ? "success" : env.status === "pending_signature" ? "warning" : "neutral"}>
                  {env.status === "pending_signature" ? "awaiting signer" : env.status}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
