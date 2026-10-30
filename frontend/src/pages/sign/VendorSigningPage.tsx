import { useEffect, useRef, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { takeTokenFromUrl } from "@/api/auth";
import { ApiError } from "@/api/client";
import { contractsApi } from "@/api/contracts";
import { Wordmark } from "@/components/auth/AuthLayout";
import { EmbeddedSigning } from "@/components/contracts/EmbeddedSigning";
import { InlineError } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { formatDateTime } from "@/lib/format";
import type { VendorSigningSession } from "@/types/api";

// The link's token survives a reload of this tab (it leaves the address bar).
const STORE_KEY = "vendor-signing-token";

function linkToken(): string | null {
  const fromUrl = takeTokenFromUrl();
  try {
    if (fromUrl) sessionStorage.setItem(STORE_KEY, fromUrl);
    return fromUrl ?? sessionStorage.getItem(STORE_KEY);
  } catch {
    return fromUrl;
  }
}

/**
 * Opened from the vendor's email (/sign#token=…), no account needed. Shows
 * what they are signing and Documenso's signing frame, on the platform's
 * own page. The contract is signed once Documenso's webhook reports it.
 */
export function VendorSigningPage() {
  const token = useRef<string | null>(linkToken());
  const [session, setSession] = useState<VendorSigningSession | null>(null);
  const [error, setError] = useState<string | null>(token.current ? null : "This page needs the link from your email.");
  const [finishing, setFinishing] = useState(false);

  const load = async () => {
    if (!token.current) return null;
    try {
      const s = (await contractsApi.vendorSigningSession(token.current)).data;
      setSession(s);
      return s;
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't open this contract. Try the link again later.");
      return null;
    }
  };

  useEffect(() => {
    document.title = "Sign contract · Procurement";
    load();
    // Once, on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // After signing, wait for Documenso's webhook to record it.
  const finished = async () => {
    setFinishing(true);
    for (let i = 0; i < 12; i++) {
      const s = await load();
      if (s?.state === "signed") break;
      await new Promise((r) => setTimeout(r, 1000));
    }
    setFinishing(false);
  };

  return (
    <div className="min-h-screen bg-paper px-4 pb-12 pt-8 sm:px-8">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
        <Wordmark />
        {error && <InlineError message={error} />}
        {!error && !session && <Skeleton className="h-64" />}
        {session && (
          <>
            <div className="rounded border border-rule bg-sheet px-5 py-4">
              <h1 className="text-title font-semibold text-ink">{session.title}</h1>
              <p className="mt-1 text-sm text-ink-2">
                Between {session.company_name} and {session.vendor_name}. Signing for {session.vendor_name}:{" "}
                <span className="text-ink">{session.signer_name}</span> ({session.signer_email})
              </p>
              {session.company_signed_at && (
                <p className="mt-1 text-sm text-ink-2">
                  Signed for {session.company_name} by {session.company_signer} on{" "}
                  {formatDateTime(session.company_signed_at)}.
                </p>
              )}
            </div>

            {session.state === "signed" && (
              <div className="flex items-start gap-2 rounded border border-success-500/30 bg-success-50 px-4 py-3 text-sm text-ink">
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success-600" />
                <span>
                  Signed{session.signed_at ? ` on ${formatDateTime(session.signed_at)}` : ""}. Both parties have now
                  signed; the executed copy is sealed with a digital certificate. You can close this page.
                </span>
              </div>
            )}
            {session.state === "expired" && (
              <InlineError message="This link has expired. Ask your contact at the company to send a new one." />
            )}
            {session.state === "closed" && (
              <InlineError message="This contract is no longer waiting for your signature." />
            )}
            {session.state === "ready" && session.host && session.token && (
              finishing ? (
                <p className="py-10 text-center text-sm text-ink-2" aria-live="polite">
                  Signed. Recording your signature…
                </p>
              ) : (
                <>
                  <p className="text-sm text-ink-2">
                    Read the agreement, then sign on the line for the vendor. {session.legal_basis}
                  </p>
                  <EmbeddedSigning
                    host={session.host}
                    token={session.token}
                    name={session.signer_name}
                    onCompleted={finished}
                    onDeclined={() => load()}
                  />
                </>
              )
            )}
          </>
        )}
      </div>
    </div>
  );
}
