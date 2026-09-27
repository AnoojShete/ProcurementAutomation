import { useCallback, useEffect, useState } from "react";
import { Search } from "lucide-react";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { usePageHeader } from "@/hooks/usePageTitle";
import type { AccountUser, Role } from "@/types/api";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { ErrorState, InlineError } from "@/components/ui/ErrorState";
import { ROLE_LABELS } from "@/lib/roleNav";
import { formatDateTime } from "@/lib/format";

const ROLES: Role[] = ["requester", "approver", "finance", "admin"];

export function UsersPage() {
  usePageHeader("Users");
  const { user: me } = useAuth();
  const [users, setUsers] = useState<AccountUser[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async (q: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      setUsers((await authApi.listUsers(q.trim() || undefined)).data);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Couldn't load users.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void load(query), 250);
    return () => clearTimeout(t);
  }, [query, load]);

  const update = async (
    u: AccountUser,
    changes: { role?: Role; is_active?: boolean },
  ) => {
    setBusy(u.id);
    setActionError(null);
    try {
      const updated = (await authApi.updateUser(u.id, changes)).data;
      setUsers((list) => list.map((x) => (x.id === u.id ? updated : x)));
    } catch (e) {
      setActionError(
        e instanceof ApiError ? e.message : "Couldn't update the user.",
      );
    } finally {
      setBusy(null);
    }
  };

  const columns: Column<AccountUser>[] = [
    {
      key: "email",
      header: "Email",
      render: (u) => (
        <span className="font-medium text-slate-900">{u.email}</span>
      ),
      sortValue: (u) => u.email,
    },
    {
      key: "role",
      header: "Role",
      render: (u) => (
        <select
          aria-label={`Role for ${u.email}`}
          className="field h-8 w-36 py-0"
          value={u.role}
          disabled={u.id === me?.id || busy === u.id}
          onChange={(e) => void update(u, { role: e.target.value as Role })}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABELS[r]}
            </option>
          ))}
        </select>
      ),
      sortValue: (u) => u.role,
    },
    {
      key: "status",
      header: "Status",
      render: (u) =>
        !u.is_active ? (
          <Badge tone="danger">Disabled</Badge>
        ) : u.email_verified_at ? (
          <Badge tone="success">Active</Badge>
        ) : (
          <Badge tone="warning">Awaiting email confirmation</Badge>
        ),
    },
    {
      key: "last_login",
      header: "Last sign-in",
      render: (u) => formatDateTime(u.last_login_at),
      hideOnMobile: true,
      sortValue: (u) => u.last_login_at ?? "",
    },
    {
      key: "created",
      header: "Created",
      render: (u) => formatDateTime(u.created_at),
      hideOnMobile: true,
      sortValue: (u) => u.created_at ?? "",
    },
    {
      key: "actions",
      header: "",
      render: (u) =>
        u.id === me?.id ? (
          <span className="text-xs text-slate-400">You</span>
        ) : (
          <Button
            size="sm"
            variant={u.is_active ? "secondary" : "primary"}
            loading={busy === u.id}
            onClick={() => void update(u, { is_active: !u.is_active })}
          >
            {u.is_active ? "Disable" : "Enable"}
          </Button>
        ),
    },
  ];

  if (loadError)
    return <ErrorState message={loadError} onRetry={() => void load(query)} />;

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        New sign-ups start as requesters. Changing a role or disabling an
        account signs that person out within the access-token lifetime.
      </p>
      {actionError && <InlineError message={actionError} />}
      <div className="relative max-w-xs">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
        <input
          className="field pl-8"
          placeholder="Search by email"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <Card>
        <DataTable
          columns={columns}
          rows={users}
          rowKey={(u) => u.id}
          loading={loading}
          emptyTitle="No users match"
        />
      </Card>
    </div>
  );
}
