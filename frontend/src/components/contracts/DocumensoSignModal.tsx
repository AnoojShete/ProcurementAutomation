import { useEffect, useState } from "react";
import { FileSignature } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { InlineError } from "@/components/ui/ErrorState";
import { contractsApi } from "@/api/contracts";
import { ApiError } from "@/api/client";
import type { Contract, SigningSession } from "@/types/api";
import { VendorRiskPanel } from "./VendorRiskPanel";
import { EmbeddedSigning } from "./EmbeddedSigning";

/**
 * The company's signatory signs a contract that is out in Documenso,
 * without leaving the platform: the vendor's risk first (BR-6, acknowledged
 * when needed), then Documenso's signing frame. After they sign, the
 * webhook records it and emails the vendor their link; this waits for that
 * before closing.
 */
export function DocumensoSignModal({
  open,
  onClose,
  contract,
  onSigned,
}: {
  open: boolean;
  onClose: () => void;
  contract: Contract;
  onSigned: () => void;
}) {
  const risk = contract.vendor_risk;
  const blocked = !!risk?.signing_blocked;
  const needsRiskAck = !blocked && !!risk?.acknowledgement_required;
  const [riskAck, setRiskAck] = useState(false);
  const [session, setSession] = useState<SigningSession | null>(null);
  const [opening, setOpening] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setRiskAck(false);
      setSession(null);
      setWaiting(false);
      setError(null);
    }
  }, [open]);

  const start = async () => {
    setOpening(true);
    setError(null);
    try {
      setSession((await contractsApi.signingSession(contract.id, needsRiskAck && riskAck)).data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't open the contract for signing.");
    } finally {
      setOpening(false);
    }
  };

  // Documenso's webhook usually lands within a second or two.
  const finished = async () => {
    setWaiting(true);
    for (let i = 0; i < 12; i++) {
      try {
        const c = (await contractsApi.get(contract.id)).data;
        if (c.signers?.find((s) => s.party === "company")?.status === "signed") break;
      } catch {
        // keep waiting; the page reloads below either way
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    onSigned();
  };

  return (
    <Modal open={open} onClose={onClose} title="Sign contract" size="xl">
      <div className="flex flex-col gap-4 text-sm">
        {error && <InlineError message={error} />}
        {waiting ? (
          <p className="py-10 text-center text-ink-2" aria-live="polite">
            Signed. Recording your signature and sending the vendor their link…
          </p>
        ) : session ? (
          <>
            <p className="text-ink-2">
              Read the contract, then sign on the line for the company. {session.legal_basis}
            </p>
            {/* Fits the dialog's body (70vh), so only the frame scrolls. */}
            <EmbeddedSigning
              host={session.host}
              token={session.token}
              name={session.name}
              onCompleted={finished}
              height="h-[calc(70vh-8.5rem)] min-h-[380px]"
            />
          </>
        ) : (
          <>
            <p className="text-ink-2">
              You sign first, here on the platform. The vendor is then emailed a link to sign on the platform too.
              Once both have signed, the signed copy is sealed with a digital certificate and a record of who signed
              and when.
            </p>
            {risk && <VendorRiskPanel risk={risk} compact />}
            {needsRiskAck && (
              <label className="flex cursor-pointer items-start gap-2.5 px-1">
                <input
                  type="checkbox"
                  checked={riskAck}
                  onChange={(e) => setRiskAck(e.target.checked)}
                  className="mt-0.5 size-4 rounded border-rule"
                />
                <span className="text-13 leading-relaxed text-ink">
                  I have reviewed this vendor's risk and accept it for this contract. This acknowledgement is kept in
                  the contract's audit trail.
                </span>
              </label>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={onClose}>
                Cancel
              </Button>
              <Button
                icon={<FileSignature className="size-4" />}
                loading={opening}
                disabled={blocked || (needsRiskAck && !riskAck)}
                onClick={start}
              >
                Open the contract to sign
              </Button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
