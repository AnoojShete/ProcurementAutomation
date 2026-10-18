import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Bell, Boxes, CheckCheck, Files, FileText, ScrollText, ShieldAlert } from "lucide-react";
import { usePageHeader } from "@/hooks/usePageTitle";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/hooks/useAuth";
import { usePeople } from "@/hooks/usePeople";
import { useUnreadNotifications } from "@/hooks/useUnreadNotifications";
import { notificationsApi } from "@/api/notifications";
import { ApiError } from "@/api/client";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Tabs } from "@/components/ui/Tabs";
import { ErrorState, InlineError } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { SkeletonTable } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { formatDateTime, titleCase } from "@/lib/format";
import type { FeedEntry, NotificationLogEntry } from "@/types/api";

const CATEGORY_ICON: Record<string, typeof Bell> = {
  approval: ScrollText,
  contract: FileText,
  risk: ShieldAlert,
  vendor: ShieldAlert,
  inventory: Boxes,
  license: Boxes,
  document: Files,
};

// Where a notification's related id lives, by event family.
const ITEM_PATH: Record<string, string> = {
  approval: "/app/requests/",
  contract: "/app/contracts/",
  risk: "/app/vendors/",
  vendor: "/app/vendors/",
  document: "/app/documents/",
  license: "/app/licenses/",
};

function family(eventType: string) {
  return eventType.split(".")[0];
}

// Generic sends (notification.send) carry their real kind only in the
// subject, e.g. "Notification: contract_ready_for_signature".
const GENERIC = /^Notification: (\w+)$/;

function kind(n: NotificationLogEntry): string {
  const generic = n.subject?.match(GENERIC)?.[1];
  return generic ? generic.split("_")[0] : family(n.event_type);
}

function itemPath(n: NotificationLogEntry): string | null {
  const base = ITEM_PATH[kind(n)];
  return base && n.related_entity_id ? base + n.related_entity_id : null;
}

function subjectOf(n: NotificationLogEntry): string | null {
  const generic = n.subject?.match(GENERIC)?.[1];
  if (generic) {
    const text = generic.replace(/_/g, " ");
    return text[0].toUpperCase() + text.slice(1);
  }
  return n.subject;
}

const STAFF = ["approver", "finance", "admin"];

/** Important = what the bell counts (urgent, delivered, yours or your
 * role's mailbox). History = everything sent to you, routine updates
 * included. System log = every notification, for staff. */
export function NotificationsPage() {
  usePageHeader("Notifications");
  const { user } = useAuth();
  const { nameFor, withNames } = usePeople();
  const { setUnread } = useUnreadNotifications();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "important";
  const isStaff = STAFF.includes(user?.role ?? "");

  const feed = useApi(
    () => (tab === "system" ? notificationsApi.log({ limit: 200 }) : notificationsApi.feed(tab === "history" ? "all" : "important", 200)),
    [tab],
  );
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const [marking, setMarking] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const rows = useMemo(
    () =>
      ((feed.data ?? []) as (FeedEntry | NotificationLogEntry)[]).map((n) => ({
        ...n,
        read: tab === "system" ? true : "read" in n ? n.read || readIds.has(n.id) : true,
      })),
    [feed.data, readIds, tab],
  );
  const unreadHere = rows.filter((n) => !n.read).length;

  const open = async (n: (typeof rows)[number]) => {
    if (!n.read) {
      setReadIds((s) => new Set(s).add(n.id));
      try {
        setUnread((await notificationsApi.markRead(n.id)).data.unread);
      } catch {
        // Still open the item; the count re-syncs on the next page change.
      }
    }
    const to = itemPath(n);
    if (to) navigate(to);
  };

  const markAll = async () => {
    setMarking(true);
    setActionError(null);
    try {
      setUnread((await notificationsApi.markAllRead()).data.unread);
      setReadIds(new Set(rows.map((n) => n.id)));
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : "Couldn't mark them as read.");
    } finally {
      setMarking(false);
    }
  };

  const tabs = [
    { key: "important", label: "Important", count: tab === "important" && unreadHere ? unreadHere : undefined },
    { key: "history", label: "History" },
    ...(isStaff ? [{ key: "system", label: "System log" }] : []),
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          <Tabs tabs={tabs} active={tab} onChange={(k) => setParams(k === "important" ? {} : { tab: k }, { replace: true })} />
        </div>
        {tab !== "system" && unreadHere > 0 && (
          <Button size="sm" variant="secondary" icon={<CheckCheck className="size-3.5" />} loading={marking} onClick={markAll}>
            Mark all as read
          </Button>
        )}
      </div>
      {actionError && <InlineError message={actionError} />}

      {feed.error ? (
        <ErrorState message={feed.error} onRetry={feed.reload} />
      ) : (
        <Card>
          <CardBody>
            {feed.loading && !feed.data ? (
              <SkeletonTable cols={3} />
            ) : rows.length === 0 ? (
              <EmptyState icon={Bell} title={tab === "important" ? "You're all caught up" : "No notifications"} />
            ) : (
              <ul className="-my-3 flex flex-col divide-y divide-rule">
                {rows.map((n) => {
                  const Icon = CATEGORY_ICON[kind(n)] ?? Bell;
                  const clickable = !n.read || !!itemPath(n);
                  const forSomeoneElse = n.recipient.toLowerCase() !== user?.email.toLowerCase();
                  const body = (
                    <>
                      <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded bg-sheet-sunk text-ink-3">
                        <Icon className="size-4" strokeWidth={1.75} aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className={cn("text-sm", n.read ? "text-ink-2" : "font-semibold text-ink")}>
                            {withNames(subjectOf(n)) || titleCase(n.event_type)}
                          </span>
                          {tab === "system" && n.status === "failed" && <Badge tone="danger">Failed</Badge>}
                        </span>
                        <span className="mt-0.5 block text-caption text-ink-3">
                          {formatDateTime(n.sent_at ?? n.created_at)}
                          {forSomeoneElse && ` · to ${nameFor(n.recipient)}`}
                        </span>
                      </span>
                      {!n.read && <span className="mt-2 size-2 shrink-0 rounded-full bg-accent" aria-label="Unread" />}
                    </>
                  );
                  return (
                    <li key={n.id}>
                      {clickable ? (
                        <button
                          type="button"
                          onClick={() => void open(n)}
                          className="-mx-4 flex w-[calc(100%+2rem)] items-start gap-3 px-4 py-3 text-left transition-colors duration-1 hover:bg-sheet-sunk focus-visible:ring-inset focus-visible:ring-offset-0 sm:-mx-5 sm:w-[calc(100%+2.5rem)] sm:px-5"
                        >
                          {body}
                        </button>
                      ) : (
                        <div className="flex items-start gap-3 py-3">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
