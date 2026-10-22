import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { authApi } from "@/api/auth";
import { ApiError } from "@/api/client";
import type { AccountUser } from "@/types/api";

interface ChangeEmailModalProps {
  user: AccountUser | null;
  isSelf?: boolean;
  onClose: () => void;
  onSaved: (updatedUser: AccountUser) => void;
}

export function ChangeEmailModal({
  user,
  isSelf = false,
  onClose,
  onSaved,
}: ChangeEmailModalProps) {
  const [newEmail, setNewEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setNewEmail("");
      setError(null);
    }
  }, [user]);

  if (!user) return null;

  const trimmed = newEmail.trim().toLowerCase();
  const isUnchanged = !trimmed || trimmed === user.email.toLowerCase();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isUnchanged) return;

    setBusy(true);
    setError(null);
    try {
      const res = await authApi.updateUser(user.id, { email: trimmed });
      onSaved(res.data);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Unable to update email address. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={Boolean(user)}
      onClose={busy ? () => {} : onClose}
      title="Change Email Address"
      size="sm"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={busy}
          >
            Cancel
          </Button>
          <Button
            type="button"
            loading={busy}
            disabled={isUnchanged}
            onClick={handleSubmit}
          >
            Update email
          </Button>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        {error && <InlineError message={error} />}

        <div className="rounded-lg border border-rule bg-sheet-sunk/50 p-3 text-sm">
          <div className="text-xs font-medium text-ink-3">Current account</div>
          <div className="mt-0.5 font-medium text-ink">
            {user.display_name ? `${user.display_name} (${user.email})` : user.email}
          </div>
        </div>

        <div>
          <label htmlFor="new-user-email" className="mb-1.5 block text-xs font-medium text-ink">
            New work email address
          </label>
          <input
            id="new-user-email"
            type="email"
            required
            autoFocus
            className="field w-full"
            placeholder="e.g. user@example.com"
            value={newEmail}
            onChange={(e) => {
              setNewEmail(e.target.value);
              setError(null);
            }}
          />
        </div>

        {isSelf ? (
          <div className="rounded border border-amber-300 bg-amber-50 p-2.5 text-xs text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
            <strong>Warning:</strong> You are changing your own email address. Updating it will invalidate your active session, and you will need to sign in again with your new email.
          </div>
        ) : (
          <p className="text-xs text-ink-3">
            The user&apos;s active sessions will be invalidated immediately. They will need to sign in with this new email address and their current password.
          </p>
        )}
      </form>
    </Modal>
  );
}
