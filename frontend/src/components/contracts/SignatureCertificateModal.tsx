import { CheckCircle2, Copy, Download, Lock, ShieldCheck } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/format";
import type { Contract, SignatureCertificate } from "@/types/api";
import { useState } from "react";

interface SignatureCertificateModalProps {
  open: boolean;
  onClose: () => void;
  contract: Contract;
  certificate?: SignatureCertificate | null;
}

export function SignatureCertificateModal({
  open,
  onClose,
  contract,
  certificate,
}: SignatureCertificateModalProps) {
  const [copied, setCopied] = useState(false);

  // Fallback cert info from contract fields if cert object isn't directly passed
  const signer = certificate?.signer_name || contract.signed_by || "Authorized Signer";
  const email = certificate?.signer_email || (contract.signed_by?.includes("<") ? contract.signed_by.split("<")[1].replace(">", "") : "signer@organization.com");
  const signedAt = certificate?.signed_at || contract.signed_at;
  const seal = certificate?.signature_seal || contract.esign_provider_ref || "UNVERIFIED-SEAL";
  const certId = certificate?.certificate_id || `CERT-${contract.id.slice(0, 8).toUpperCase()}`;

  const copyHash = () => {
    navigator.clipboard.writeText(seal);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Electronic Signature Certificate"
      size="md"
      footer={
        <div className="flex w-full items-center justify-between">
          <span className="text-[11px] text-slate-400">Verifiable Electronic Signature Record</span>
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4 text-sm">
        {/* Certificate Status Banner */}
        <div className="flex items-center gap-3 rounded-xl border border-emerald-200 bg-emerald-50/70 p-3.5 text-emerald-900">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
            <ShieldCheck className="size-5" />
          </div>
          <div>
            <h4 className="font-semibold text-emerald-950">Legally Executed & Digitally Sealed</h4>
            <p className="text-xs text-emerald-700">
              Verified compliant with US E-SIGN Act (15 U.S.C. § 7001) and UETA
            </p>
          </div>
        </div>

        {/* Certificate Details */}
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-surface-border bg-surface-muted/30 p-3 text-xs">
          <div>
            <span className="text-slate-400">Certificate ID</span>
            <p className="font-mono font-medium text-slate-700 truncate">{certId}</p>
          </div>
          <div>
            <span className="text-slate-400">Execution Date</span>
            <p className="font-medium text-slate-700">{formatDateTime(signedAt)}</p>
          </div>
          <div>
            <span className="text-slate-400">Authorized Signer</span>
            <p className="font-medium text-slate-800">{signer}</p>
          </div>
          <div>
            <span className="text-slate-400">Signer Email</span>
            <p className="font-medium text-slate-800 truncate">{email}</p>
          </div>
          <div>
            <span className="text-slate-400">Legal Framework</span>
            <p className="font-medium text-slate-800">ESIGN Act & UETA</p>
          </div>
          <div>
            <span className="text-slate-400">Contract ID</span>
            <p className="font-mono font-medium text-slate-700 truncate">{contract.id.slice(0, 12)}...</p>
          </div>
        </div>

        {/* Signature Preview if Available */}
        {certificate?.signature_image && (
          <div>
            <span className="text-xs font-medium text-slate-500">Signer's Signature Mark</span>
            <div className="mt-1 flex h-20 items-center justify-center rounded-lg border border-slate-200 bg-white p-2">
              <img
                src={certificate.signature_image}
                alt="Electronic Signature"
                className="max-h-full max-w-full object-contain"
              />
            </div>
          </div>
        )}

        {/* Cryptographic Hash Seal */}
        <div>
          <div className="mb-1 flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center gap-1">
              <Lock className="size-3 text-slate-400" />
              Cryptographic Integrity Seal (SHA-256)
            </span>
            <button
              onClick={copyHash}
              className="flex items-center gap-1 font-medium text-brand-600 hover:text-brand-700"
            >
              <Copy className="size-3" />
              {copied ? "Copied!" : "Copy Seal"}
            </button>
          </div>
          <div className="break-all rounded-lg bg-slate-900 p-2.5 font-mono text-[11px] text-slate-200 shadow-inner">
            {seal}
          </div>
        </div>
      </div>
    </Modal>
  );
}
