import { useEffect, useRef, useState } from "react";
import { Eye, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { ApiError } from "@/api/client";
import {
  notificationsApi,
  type NotificationTemplate,
  type NotificationTemplateSummary,
} from "@/api/notifications";
import { useApi } from "@/hooks/useApi";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { StatusDot } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { InlineError } from "@/components/ui/ErrorState";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/cn";

const NEW = "__new__";

function message(e: unknown) {
  return e instanceof ApiError ? e.message : "Couldn't reach the notification service.";
}

/** Notification templates: every email the platform sends, editable here
 * without a code change. A built-in's edit is stored as an override (reset
 * brings the default back); new templates are sent by name through
 * notification.send. */
export function TemplateManager() {
  const { data: list, error, reload } = useApi(() => notificationsApi.templates(), []);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && list?.length) setSelected(list[0].name);
  }, [list, selected]);

  if (!list) return error ? <InlineError message={error} /> : <Skeleton className="h-96" />;

  return (
    <Card className="grid grid-cols-1 lg:grid-cols-[18rem_1fr]">
      <div className="border-b border-rule lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-2 border-b border-rule px-4 py-3">
          <h3 className="text-heading font-semibold text-ink">Templates</h3>
          <Button size="sm" variant="secondary" icon={<Plus className="size-3.5" />} onClick={() => setSelected(NEW)}>
            New
          </Button>
        </div>
        <ul className="max-h-[36rem] divide-y divide-rule overflow-y-auto scrollbar-thin">
          {list.map((t) => (
            <li key={t.name}>
              <button
                type="button"
                onClick={() => setSelected(t.name)}
                className={cn(
                  "flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors duration-1 hover:bg-sheet-sunk",
                  selected === t.name && "bg-sheet-sunk",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-13 text-ink">{t.name}</span>
                  <TemplateState t={t} />
                </span>
                <span className="truncate text-13 text-ink-3">{t.event}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-w-0">
        {selected === NEW ? (
          <TemplateEditor
            key={NEW}
            creating
            onSaved={(name) => {
              reload();
              setSelected(name);
            }}
          />
        ) : selected ? (
          <TemplateLoader key={selected} name={selected} onChanged={reload} onDeleted={() => { setSelected(null); reload(); }} />
        ) : null}
      </div>
    </Card>
  );
}

function TemplateState({ t }: { t: NotificationTemplateSummary }) {
  if (!t.enabled) return <StatusDot tone="danger">Off</StatusDot>;
  if (t.is_custom) return <StatusDot tone="brand">Custom</StatusDot>;
  if (t.customised) return <StatusDot tone="warning">Edited</StatusDot>;
  return <StatusDot tone="neutral">Default</StatusDot>;
}

function TemplateLoader({ name, onChanged, onDeleted }: { name: string; onChanged: () => void; onDeleted: () => void }) {
  const { data, error, reload } = useApi(() => notificationsApi.template(name), [name]);
  if (!data) return <div className="p-5">{error ? <InlineError message={error} /> : <Skeleton className="h-80" />}</div>;
  return (
    <TemplateEditor
      key={`${data.name}-${data.updated_at}`}
      template={data}
      onSaved={() => {
        reload();
        onChanged();
      }}
      onDeleted={onDeleted}
    />
  );
}

function TemplateEditor({
  template,
  creating,
  onSaved,
  onDeleted,
}: {
  template?: NotificationTemplate;
  creating?: boolean;
  onSaved: (name: string) => void;
  onDeleted?: () => void;
}) {
  const [name, setName] = useState("");
  const [subject, setSubject] = useState(template?.subject ?? "");
  const [body, setBody] = useState(template?.body ?? "");
  const [recipients, setRecipients] = useState((template?.extra_recipients ?? []).join(", "));
  const [enabled, setEnabled] = useState(template?.enabled ?? true);
  const [description, setDescription] = useState(template?.description ?? "");
  const [busy, setBusy] = useState<"save" | "reset" | "preview" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ subject: string; body: string } | null>(null);
  const bodyRef = useRef<HTMLTextAreaElement>(null);

  const placeholders = template?.placeholders ?? [];
  const extra = recipients.split(/[,;]/).map((r) => r.trim()).filter(Boolean);

  const insert = (p: string) => {
    const el = bodyRef.current;
    const token = `{{ ${p} }}`;
    if (!el) return setBody((b) => b + token);
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    setBody(body.slice(0, start) + token + body.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const run = async (kind: "save" | "reset" | "preview", fn: () => Promise<void>) => {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(null);
    }
  };

  const save = () =>
    run("save", async () => {
      const input = { subject, body, description, extra_recipients: extra, enabled };
      if (creating) {
        const { data } = await notificationsApi.createTemplate({ ...input, name: name.trim() });
        onSaved(data.name);
      } else if (template) {
        await notificationsApi.updateTemplate(template.name, input);
        setNotice("Saved. The next email uses this text.");
        onSaved(template.name);
      }
    });

  const reset = () =>
    run("reset", async () => {
      if (!template) return;
      await notificationsApi.resetTemplate(template.name);
      if (template.is_custom) onDeleted?.();
      else onSaved(template.name);
    });

  const showPreview = () =>
    run("preview", async () => {
      const { data } = await notificationsApi.previewTemplate(template?.name ?? "generic_fallback", subject, body);
      setPreview(data);
    });

  return (
    <div>
      <CardHeader
        title={creating ? "New template" : <span className="font-mono">{template?.name}</span>}
        subtitle={
          creating
            ? "Other services send it by name through notification.send."
            : `Sent on ${template?.event}, to ${template?.recipient?.toLowerCase()}.`
        }
        action={
          template?.updated_by ? (
            <span className="text-13 text-ink-3">
              Edited by {template.updated_by} {formatRelativeTime(template.updated_at)}
            </span>
          ) : undefined
        }
      />
      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {creating && (
          <label className="flex flex-col gap-1 text-13 text-ink-2">
            Name
            <input
              className="field font-mono"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="quarterly_vendor_review"
            />
            <span className="text-ink-3">Lower-case letters, digits and underscores.</span>
          </label>
        )}
        {(creating || template?.is_custom) && (
          <label className="flex flex-col gap-1 text-13 text-ink-2">
            What it is for
            <input className="field" value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
        )}
        <label className="flex flex-col gap-1 text-13 text-ink-2">
          Subject
          <input className="field" value={subject} onChange={(e) => setSubject(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-13 text-ink-2">
          Message body
          <textarea
            ref={bodyRef}
            className="field h-72 py-2 font-mono text-13 leading-relaxed sm:h-72"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            spellCheck={false}
          />
        </label>
        {placeholders.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-13 text-ink-2">
              Placeholders {template?.placeholders_fixed ? "this email can use" : "in this template"} (click to insert)
            </span>
            <div className="flex flex-wrap gap-1.5">
              {placeholders.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => insert(p)}
                  className="rounded-sm border border-rule bg-sheet-sunk px-1.5 py-0.5 font-mono text-13 text-ink-2 hover:border-rule-strong hover:text-ink"
                >
                  {`{{ ${p} }}`}
                </button>
              ))}
            </div>
          </div>
        )}
        <label className="flex flex-col gap-1 text-13 text-ink-2">
          Also send a copy to
          <input
            className="field"
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            placeholder="audit@company.com, cfo@company.com"
          />
          <span className="text-ink-3">
            Comma-separated. {creating ? "The sender names the main recipient." : `The main recipient is ${template?.recipient?.toLowerCase()}.`}
          </span>
        </label>
        <label className="flex items-center gap-2 text-sm text-ink">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="size-4 accent-accent" />
          Send this email
          {!enabled && <span className="text-13 text-ink-3">(turned off: logged as skipped, nothing sent)</span>}
        </label>

        {error && <InlineError message={error} />}
        {notice && <p className="text-13 text-success-700">{notice}</p>}

        <div className="flex flex-wrap gap-2">
          <Button onClick={save} loading={busy === "save"} icon={<Save className="size-4" />}>
            {creating ? "Create template" : "Save"}
          </Button>
          <Button variant="secondary" onClick={showPreview} loading={busy === "preview"} icon={<Eye className="size-4" />}>
            Preview
          </Button>
          {template && (template.is_custom || template.customised) && (
            <Button
              variant={template.is_custom ? "destructive" : "ghost"}
              onClick={reset}
              loading={busy === "reset"}
              icon={template.is_custom ? <Trash2 className="size-4" /> : <RotateCcw className="size-4" />}
            >
              {template.is_custom ? "Delete template" : "Restore default"}
            </Button>
          )}
        </div>

        {preview && (
          <div className="rounded border border-rule bg-paper">
            <div className="border-b border-rule px-4 py-2 text-13">
              <span className="text-ink-3">Subject: </span>
              <span className="font-medium text-ink">{preview.subject}</span>
            </div>
            <pre className="max-h-80 overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-13 leading-relaxed text-ink-2">
              {preview.body}
            </pre>
            <p className="border-t border-rule px-4 py-2 text-13 text-ink-3">Sample values in [brackets]; real emails use the event's data.</p>
          </div>
        )}
      </div>
    </div>
  );
}
