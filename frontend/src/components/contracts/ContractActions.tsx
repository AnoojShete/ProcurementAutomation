import { useEffect, useState } from "react";
import { Download, FileSignature, Mail, ScrollText, ShieldCheck } from "lucide-react";
import { contractsApi } from "@/api/contracts";
import { ApiError } from "@/api/client";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { StatusDot } from "@/components/ui/Badge";
import { InlineError, InlineSuccess } from "@/components/ui/ErrorState";
import { DigitalSignatureModal } from "./DigitalSignatureModal";
import { SignatureCertificateModal } from "./SignatureCertificateModal";
import { DocumensoSignModal } from "./DocumensoSignModal";
import { formatDateTime } from "@/lib/format";
import type { Contract, ContractSigner, ContractTemplate, PurchaseRequest } from "@/types/api";

const STAFF = ["approver", "finance", "admin"];

// With Documenso set up (contract.signing_provider), both parties sign in
// its frame on the platform's pages: the company's signatory first, then the
// vendor through an emailed link. Without it, the built-in e-sign: typed or
// drawn signature, consent and a SHA-256 seal in the audit log.

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

/** Out with a real provider (Documenso document / DocuSign envelope): it
 * completes there, not in the platform. */
export function isProviderLive(contract?: Contract | null) {
  const ref = contract?.esign_provider_ref ?? "";
  return ref.startsWith("documenso-env-") || ref.startsWith("docusign-env-");
}

const SIGNER_STATUS: Record<ContractSigner["status"], [string, "neutral" | "warning" | "success" | "danger"]> = {
  waiting: ["Waiting", "neutral"],
  ready: ["To sign", "warning"],
  signed: ["Signed", "success"],
  rejected: ["Declined", "danger"],
};

/** Who signs a Documenso contract, in order, and where each one is. */
function SignerList({ signers }: { signers: ContractSigner[] }) {
  return (
    <ol className="flex flex-col gap-1.5 text-13">
      {signers.map((s) => {
        const [label, tone] = SIGNER_STATUS[s.status];
        return (
          <li key={s.party} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="w-28 shrink-0 text-ink-2">{s.party === "company" ? "For the company" : "For the vendor"}</span>
            <span className="text-ink">
              {s.name} <span className="text-ink-3">{s.email}</span>
            </span>
            <StatusDot tone={tone}>{label}</StatusDot>
            {s.signed_at && <span className="text-ink-3">{formatDateTime(s.signed_at)}</span>}
            {s.rejection_reason && <span className="text-ink-2">"{s.rejection_reason}"</span>}
          </li>
        );
      })}
    </ol>
  );
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
  const [signerEmail, setSignerEmail] = useState("");
  const [vendorEmail, setVendorEmail] = useState("");
  const [vendorName, setVendorName] = useState("");
  const [sending, setSending] = useState(false);
  const [resending, setResending] = useState(false);

  const twoParty = contract?.signing_provider === "documenso";
  const signers = contract?.signers ?? [];
  const companySigner = signers.find((s) => s.party === "company");
  const vendorSigner = signers.find((s) => s.party === "vendor");
  const inDocumenso = (contract?.esign_provider_ref ?? "").startsWith("documenso-env-");
  // Documenso: only the named company signatory, while it is their turn.
  const myTurnInDocumenso =
    inDocumenso &&
    contract?.status === "pending_signature" &&
    companySigner?.status === "ready" &&
    companySigner.email.toLowerCase() === (user?.email ?? "").toLowerCase();
  // Built-in e-sign: any staff member, unless the contract is out with a provider.
  const canSignHere =
    staff &&
    !!contract &&
    !(twoParty && contract.status === "draft") &&
    (contract.status === "draft" || (contract.status === "pending_signature" && !isProviderLive(contract)));

  const openSend = () => {
    setSignerEmail(user?.email ?? "");
    setVendorEmail(contract?.vendor_contact_email ?? "");
    setVendorName("");
    setSendOpen(true);
  };

  useEffect(() => {
    if (autoOpen === "sign" && (canSignHere || myTurnInDocumenso)) setSignOpen(true);
    // Two-party signing starts by naming the signatories.
    if (autoOpen === "sign" && twoParty && staff && contract?.status === "draft") openSend();
    if (autoOpen === "send" && staff && contract?.status === "draft") openSend();
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
      () =>
        contractsApi.sendForSignature(contract.id, {
          signer_email: signerEmail || undefined,
          provider: twoParty ? "documenso" : "builtin",
          vendor_signer_email: twoParty ? vendorEmail || undefined : undefined,
          vendor_signer_name: twoParty ? vendorName || undefined : undefined,
        }),
      twoParty
        ? `Sent. ${signerEmail} signs first, on this page; the vendor is emailed a link once they have.`
        : `Ready for ${signerEmail} to sign. Use “Sign now” to sign it in the platform.`,
      "Couldn't send for signature.",
    );
    setSending(false);
    if (ok) setSendOpen(false);
  };

  const resendVendorLink = async () => {
    if (!contract) return;
    setResending(true);
    await run(
      () => contractsApi.resendVendorLink(contract.id),
      `A new signing link was emailed to ${vendorSigner?.email}. The earlier link no longer works.`,
      "Couldn't send a new link.",
    );
    setResending(false);
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
        {contract.status === "signed" ? (
          <>
            <Button
              icon={<Download className="size-4" />}
              loading={downloading === "signed"}
              onClick={() => download("signed")}
            >
              Download signed copy
            </Button>
            <Button
              variant="secondary"
              loading={downloading === "document"}
              onClick={() => download("document")}
            >
              Original PDF (unsigned)
            </Button>
          </>
        ) : contract.status === "pending_signature" && companySigner?.status === "signed" ? (
          <>
            <Button
              icon={<Download className="size-4" />}
              loading={downloading === "signed"}
              onClick={() => download("signed")}
            >
              Download copy signed by us
            </Button>
            <Button
              variant="secondary"
              loading={downloading === "document"}
              onClick={() => download("document")}
            >
              Original PDF (unsigned)
            </Button>
          </>
        ) : (
          <Button
            variant="secondary"
            icon={<Download className="size-4" />}
            loading={downloading === "document"}
            onClick={() => download("document")}
          >
            Download PDF
          </Button>
        )}
        {contract.status === "signed" && certificate && (
          <Button variant="secondary" icon={<ShieldCheck className="size-4" />} onClick={() => setCertOpen(true)}>
            Signature certificate
          </Button>
        )}
        {staff && contract.status === "draft" && (
          <Button variant={twoParty ? "primary" : "secondary"} onClick={openSend}>
            Send for signature
          </Button>
        )}
        {(canSignHere || myTurnInDocumenso) && (
          <Button icon={<FileSignature className="size-4" />} onClick={() => setSignOpen(true)}>
            Sign now
          </Button>
        )}
        {staff &&
          inDocumenso &&
          contract.status === "pending_signature" &&
          companySigner?.status === "signed" &&
          vendorSigner?.status === "ready" && (
            <Button variant="secondary" icon={<Mail className="size-4" />} loading={resending} onClick={resendVendorLink}>
              Email the vendor a new link
            </Button>
          )}
      </div>
      {signers.length > 0 && contract.status !== "draft" && <SignerList signers={signers} />}
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
            <Button loading={sending} onClick={send} disabled={!signerEmail || (twoParty && !vendorEmail)}>
              Send
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4 text-sm">
          <div>
            <label htmlFor="signer-email" className="mb-1 block font-medium text-ink">
              {twoParty ? "Signs for the company" : "Signer email"}
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
          {twoParty ? (
            <>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="vendor-signer-name" className="mb-1 block font-medium text-ink">
                    Signs for the vendor
                  </label>
                  <input
                    id="vendor-signer-name"
                    value={vendorName}
                    onChange={(e) => setVendorName(e.target.value)}
                    placeholder="Full name"
                    className="field"
                  />
                </div>
                <div>
                  <label htmlFor="vendor-signer-email" className="mb-1 block font-medium text-ink">
                    Their email
                  </label>
                  <input
                    id="vendor-signer-email"
                    type="email"
                    value={vendorEmail}
                    onChange={(e) => setVendorEmail(e.target.value)}
                    placeholder="signatory@vendor.com"
                    className="field"
                  />
                </div>
              </div>
              <p className="text-13 text-ink-2">
                Both parties sign on this platform. The company's signatory signs first from this page; the vendor's
                signatory is then emailed a personal link to a signing page here, no account needed. The signed copy
                is sealed with a digital certificate and a record of who signed, when and from where.
              </p>
            </>
          ) : (
            <p className="text-13 text-ink-2">
              Signed with the built-in e-sign: typed or drawn signature, consent, and a SHA-256 seal in the audit log.
            </p>
          )}
        </div>
      </Modal>

      {myTurnInDocumenso ? (
        <DocumensoSignModal
          open={signOpen}
          onClose={() => setSignOpen(false)}
          contract={contract}
          onSigned={() => {
            setSignOpen(false);
            setSuccess("Signed. The vendor has been emailed a link to sign.");
            onChanged?.();
          }}
        />
      ) : (
        <DigitalSignatureModal
          open={signOpen}
          onClose={() => setSignOpen(false)}
          contract={contract}
          defaultSignerEmail={user?.email ?? ""}
          defaultSignerName={user?.display_name || user?.email?.split("@")[0].replace(/[._]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || ""}
          onSuccess={() => {
            setSignOpen(false);
            setSuccess("Contract signed. The signed copy and signature certificate are ready.");
            onChanged?.();
          }}
        />
      )}

      {certificate && (
        <SignatureCertificateModal open={certOpen} onClose={() => setCertOpen(false)} contract={contract} certificate={certificate} />
      )}
    </div>
  );
}
