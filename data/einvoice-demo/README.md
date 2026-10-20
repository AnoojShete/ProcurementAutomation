# Demo e-invoice signing key

`demo-irp-signing-key.pem` is a **published demo key**, not a secret. It signs
the QR codes of test e-invoices (`services/document-vendor-agent/scripts/gst_invoice_lib.py`,
used by `tests/e2e/gst_flow.py` and the service's tests) the way the Invoice
Registration Portal signs real ones (RS256 JWT).

Its public half is `shared/einvoice/demo-irp-public-key.pem`. The
document-vendor-agent trusts it **only when `APP_ENV=development`**; in
production it is refused and `EINVOICE_PUBLIC_KEY` must hold the portal's real
public key (docs/deployment.md). Anyone can sign with this key, so a QR it
verifies proves nothing outside the demo.

Made with `openssl genrsa 2048` on 21 Oct 2026 (feature expansion Phase 4).
