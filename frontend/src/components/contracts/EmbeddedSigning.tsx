import { useState } from "react";
import { EmbedSignDocument } from "@documenso/embed-react";
import { InlineError } from "@/components/ui/ErrorState";

/**
 * Documenso's signing frame, shown inside the platform's own page. The
 * signer reads the contract, draws or types their signature on the
 * "Signature" line and confirms; Documenso records it with its audit trail
 * and, once both parties have signed, seals the PDF with a certificate.
 * The platform learns of the signature from Documenso's webhook, so
 * `onCompleted` only tells the page to look again.
 */
export function EmbeddedSigning({
  host,
  token,
  name,
  onCompleted,
  onDeclined,
  height = "h-[78vh] min-h-[560px]",
}: {
  host: string;
  token: string;
  name: string;
  onCompleted: () => void;
  onDeclined?: () => void;
  /** Height classes for the frame; Documenso scrolls the contract inside it. */
  height?: string;
}) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="flex flex-col gap-2">
      {error && <InlineError message={error} />}
      <div className="relative overflow-hidden rounded border border-rule bg-sheet">
        {!ready && (
          <p className="absolute inset-x-0 top-6 text-center text-sm text-ink-2" aria-live="polite">
            Loading the contract…
          </p>
        )}
        <EmbedSignDocument
          host={host}
          token={token}
          name={name}
          lockName
          darkModeDisabled
          allowDocumentRejection={!!onDeclined}
          className={`block w-full ${height}`}
          onDocumentReady={() => setReady(true)}
          onDocumentCompleted={() => onCompleted()}
          onDocumentRejected={() => onDeclined?.()}
          onDocumentError={() => setError("The signing frame reported an error. Reload the page and try again.")}
        />
      </div>
    </div>
  );
}
