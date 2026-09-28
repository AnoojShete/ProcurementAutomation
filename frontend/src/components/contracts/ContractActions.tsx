import { useEffect, useState } from "react";
import { Download, FileCheck2, FileSignature, ScrollText, ShieldCheck } from "lucide-react";
import { contractsApi } from "@/api/contracts";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { DigitalSignatureModal } from "./DigitalSignatureModal";
import { SignatureCertificateModal } from "./SignatureCertificateModal";
import type { Contract, ContractTemplate, PurchaseRequest } from "@/types/api";

const STAFF = ["approver", "finance", "admin"];

type Provider = "builtin" | "documenso" | "docusign";
const PROVIDERS: [Provider, string, string][] = [
  ["builtin", "Built-in e-sign", "Sign inside the platform: typed or drawn signature, consent, and a SHA-256 seal in the audit log."],
  ["documenso", "Documenso", "Self-hosted e-signature. Emails the signer a signing link when a Documenso instance is configured."],
  ["docusign", "DocuSign (sandbox)", "Demo only. Nothing is sent; completion is simulated."],
];

const TEMPLATES: [ContractTemplate, string][] = [
  ["hardware_purchase", "Hardware Purchase Agreement"],
  ["saas_subscription", "SaaS Subscription Agreement"],
  ["professional_services", "Professional Services Agreement"],
];

function defaultTemplate(request?: PurchaseRequest | null): ContractTemplate {
  if (request?.request_type === "hardware") return "hardware_purchase";
  if (request?.request_type === "license" || request?.request_type === "saas") return "saas_subscription";
  return "professional_services";
}

export function isDocumensoLive(contract?: Contract | null) {
  return !!contract?.esign_provider_ref?.startsWith("documenso-doc-");
}

/**
 * The contract agent's actions for one contract: generate (from an approved
 * request), download, send for signature, sign in the platform, view the
 * signature certificate. Used by the contract page, the request page's
 * contract card and the lifecycle "Contract"/"Signature" steps, so signing
 * works the same everywhere. Talks only to contract-risk-agent (/contracts).
 *
 * `autoOpen="sign"` opens the signing dialog straight away (used when the
 * user clicks the lifecycle's Signature step).
 */
export function ContractActions({
  contract,
  request,
  onChanged,
  autoOpen,
  layout = "row",
}: {
  contract: Contract | null;
  request?: PurchaseRequest | null;
  onChanged?: () => void;
  autoOpen?: "sign" | "send";
  layout?: "row" | "stack";
}) {
  const { user } = useAuth();
  const staff = STAFF.includes(user?.role ?? "");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [template, setTemplate] = useState<ContractTemplate>(defaultTemplate(request));
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState<"document" | "signed" | null>(null);
  const [sendOpen, setSendOpen] = useState(false);
  const [signOpen, setSignOpen] = useState(false);
  const [certOpen, setCertOpen] = useState(false);
  const [provider, setProvider] = useState<Provider>("builtin");
  const [signerEmail, setSignerEmail] = useState("");
  const [sending, setSending] = useState(false);

  const canSignHere =
    staff && !!contract && (contract.status === "draft" || (contract.status === "pending_signature" && !isDocumensoLive(contract)));

  useEffect(() => {
    if (autoOpen === "sign" && canSignHere) setSignOpen(true);
    if (autoOpen === "send" && staff && contract?.status === "draft") {
      setSignerEmail(user?.email ?? "");
      setSendOpen(true);
    }
    // Only when the requested action or the contract changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoOpen, contract?.id]);

  const run = async (fn: () => Promise<unknown>, ok: string, fail: string) => {
    setError(null);
    setSuccess(null);
    try {
      await fn();
      setSuccess(ok);
      onChanged?.();
      return true;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : fail);
      return false;
    }
  };

  const generate = async () => {
    if (!request) return;
    setGenerating(true);
    await run(() => contractsApi.generate(request.id, template), "Contract generated.", "Couldn't generate the contract.");
    setGenerating(false);
  };

  const download = async (kind: "document" | "signed") => {
    if (!contract) return;
    setDownloading(kind);
    await run(
      () => (kind === "signed" ? contractsApi.downloadSigned(contract.id) : contractsApi.downloadDocument(contract.id)),
      "",
      "Download failed.",
    );
    setSuccess(null);
    setDownloading(null);
  };

  const send = async () => {
    if (!contract) return;
    setSending(true);
    const ok = await run(
      () => contractsApi.sendForSignature(contract.id, signerEmail || undefined, provider),
      provider === "builtin" ? "Ready to sign. Use “Sign now” to sign it in the platform." : `Sent to ${signerEmail} for signature.`,
      "Couldn't send for signature.",
    );
    setSending(false);
    if (ok) setSendOpen(false);
  };

  const wrap = layout === "row" ? "flex flex-wrap items-center gap-2" : "flex flex-col items-stretch gap-2";

  // No contract yet: only generation, once the request is approved.
  if (!contract) {
    if (!request || request.status !== "approved") {
      return <p className="text-sm text-slate-600">A contract can be generated once the request is approved.</p>;
    }
    if (!staff) return <p className="text-sm text-slate-600">Waiting for the procurement team to generate the contract.</p>;
    return (
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-slate-700" htmlFor="contract-template">
          Contract template
        </label>
        <select
          id="contract-template"
          value={template}
          onChange={(e) => setTemplate(e.target.value as ContractTemplate)}
          className="field"
        >
          {TEMPLATES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <Button loading={generating} onClick={generate} icon={<ScrollText className="size-4" />}>
          Generate contract
        </Button>
        {error && <InlineError message={error} />}
        {success && <InlineSuccess message={success} />}
      </div>
    );
  }

  const certificate = contract.signature_certificate;
  return (
    <div className="flex flex-col gap-2">
      <div className={wrap}>
        <Button
          variant="secondary"
          icon={<Download className="size-4" />}
          loading={downloading === "document"}
          onClick={() => download("document")}
        >
          {contract.status === "signed" ? "Original PDF" : "Download PDF"}
        </Button>
        {contract.status === "signed" && (
          <Button icon={<FileCheck2 className="size-4" />} loading={downloading === "signed"} onClick={() => download("signed")}>
            Download signed copy
          </Button>
        )}
        {contract.status === "signed" && certificate && (
          <Button variant="secondary" icon={<ShieldCheck className="size-4" />} onClick={() => setCertOpen(true)}>
            Signature certificate
          </Button>
        )}
        {staff && contract.status === "draft" && (
          <Button
            variant="secondary"
            onClick={() => {
              setSignerEmail(user?.email ?? "");
              setSendOpen(true);
            }}
          >
            Send for signature
          </Button>
        )}
        {canSignHere && (
          <Button icon={<FileSignature className="size-4" />} onClick={() => setSignOpen(true)}>
            Sign now
          </Button>
        )}
      </div>
      {!staff && contract.status !== "signed" && (
        <p className="text-xs text-slate-500">Signing is done by an approver, finance or admin.</p>
      )}
      {error && <InlineError message={error} />}
      {success && <InlineSuccess message={success} />}

      <Modal
        open={sendOpen}
        onClose={() => setSendOpen(false)}
        title="Send for signature"
        footer={
          <>
            <Button variant="secondary" onClick={() => setSendOpen(false)}>
              Cancel
            </Button>
            <Button loading={sending} onClick={send} disabled={!signerEmail}>
              Send
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <div>
            <label htmlFor="signer-email" className="mb-1 block font-medium text-slate-800">
              Signer email
            </label>
            <input
              id="signer-email"
              type="email"
              value={signerEmail}
              onChange={(e) => setSignerEmail(e.target.value)}
              placeholder="signer@company.com"
              className="field"
            />
          </div>
          <fieldset>
            <legend className="mb-1 font-medium text-slate-800">Provider</legend>
            <div className="divide-y divide-surface-border rounded-md border border-surface-border">
              {PROVIDERS.map(([value, name, desc]) => (
                <label key={value} className="flex cursor-pointer items-start gap-2.5 px-3 py-2.5 hover:bg-surface-subtle">
                  <input
                    type="radio"
                    name="provider"
                    value={value}
                    checked={provider === value}
                    onChange={() => setProvider(value)}
                    className="mt-0.5 accent-brand-500"
                  />
                  <span>
                    <span className="block font-medium text-slate-900">{name}</span>
                    <span className="block text-xs text-slate-500">{desc}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <p className="text-xs text-slate-500">The signer receives the contract as a PDF, the same file as “Download PDF”.</p>
        </div>
      </Modal>

      <DigitalSignatureModal
        open={signOpen}
        onClose={() => setSignOpen(false)}
        contract={contract}
        defaultSignerEmail={user?.email ?? ""}
        defaultSignerName={user?.email?.split("@")[0].replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) ?? ""}
        onSuccess={() => {
          setSignOpen(false);
          setSuccess("Contract signed. The signed copy and signature certificate are ready.");
          onChanged?.();
        }}
      />

      {certificate && (
        <SignatureCertificateModal open={certOpen} onClose={() => setCertOpen(false)} contract={contract} certificate={certificate} />
      )}
    </div>
  );
}
