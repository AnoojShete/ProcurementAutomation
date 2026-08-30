import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { contractsApi } from "@/api/contracts";
import { CONTRACT_TEMPLATES } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { ContractTemplate } from "@/types/api";

export function GenerateContractModal({
  open,
  onClose,
  onGenerated,
  purchaseRequestId,
}: {
  open: boolean;
  onClose: () => void;
  onGenerated: (contractId: string) => void;
  purchaseRequestId?: string;
}) {
  const [requestId, setRequestId] = useState(purchaseRequestId ?? "");
  const [template, setTemplate] = useState<ContractTemplate>("hardware_purchase");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!requestId.trim()) {
      setError("Enter the purchase request ID this contract is generated from.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await contractsApi.generate(requestId.trim(), template);
      onGenerated(res.data.id);
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unable to generate contract — the request may not be approved yet.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Generate a contract">
      <div className="flex flex-col gap-3">
        <p className="text-sm text-slate-500">Generates a contract from an approved purchase request.</p>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Purchase Request ID</span>
          <input
            value={requestId}
            onChange={(e) => setRequestId(e.target.value)}
            placeholder="uuid"
            disabled={!!purchaseRequestId}
            className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500 disabled:bg-surface-muted"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Template</span>
          <select
            value={template}
            onChange={(e) => setTemplate(e.target.value as ContractTemplate)}
            className="w-full rounded-lg border border-surface-border px-3 py-2 text-sm focus:border-brand-500"
          >
            {CONTRACT_TEMPLATES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        {error && <InlineError message={error} />}
        <Button loading={submitting} onClick={submit}>
          Generate
        </Button>
      </div>
    </Modal>
  );
}
