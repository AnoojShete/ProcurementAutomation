import { useParams } from "react-router-dom";
import { authApi } from "@/api/auth";
import { useApi } from "@/hooks/useApi";
import { usePageHeader } from "@/hooks/usePageTitle";
import { Section } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { DocketHeader } from "@/components/ui/DocketHeader";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { ROLE_LABELS } from "@/lib/roleNav";
import { formatDateTime } from "@/lib/format";

/** One person's profile, opened from their name anywhere in the app
 * (admins). Role and access changes stay on the Users page. */
export function UserProfilePage() {
  const { id = "" } = useParams();
  const { data: user, loading, error, reload } = useApi(() => authApi.getUser(id), [id]);
  usePageHeader(user?.display_name || user?.email || "User", "Users");

  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (loading && !user) return <Skeleton className="h-40" />;
  if (!user) return null;

  return (
    <div className="flex max-w-2xl flex-col gap-6">
      <DocketHeader
        reference={ROLE_LABELS[user.role]}
        title={user.display_name || user.email}
        status={
          !user.is_active ? (
            <Badge tone="danger">Disabled</Badge>
          ) : user.email_verified_at ? (
            <Badge tone="success">Active</Badge>
          ) : (
            <Badge tone="warning">Awaiting email confirmation</Badge>
          )
        }
      />
      <Section title="Profile">
        <dl className="grid grid-cols-[140px_1fr] gap-y-2 text-sm">
          <dt className="text-ink-3">Name</dt>
          <dd className="text-ink">{user.display_name || "—"}</dd>
          <dt className="text-ink-3">Email</dt>
          <dd className="text-ink">{user.email}</dd>
          <dt className="text-ink-3">Role</dt>
          <dd className="text-ink">{ROLE_LABELS[user.role]}</dd>
          <dt className="text-ink-3">Last sign-in</dt>
          <dd className="text-ink">{formatDateTime(user.last_login_at)}</dd>
          <dt className="text-ink-3">Created</dt>
          <dd className="text-ink">{formatDateTime(user.created_at)}</dd>
        </dl>
      </Section>
    </div>
  );
}
