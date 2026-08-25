"""Thin client interface for a self-hosted e-signature provider
(OpenSign/Documenso). Routes a contract for signature and returns a
provider reference. The actual "signed" callback arrives asynchronously
via the webhook added in the platform-wide hardening pass
(POST /webhooks/esign) — this client only kicks off the signature request.

There's no live OpenSign/Documenso instance in this dev/demo stack, so
`request_signature` simulates the provider's synchronous "request accepted"
response deterministically from the contract id. Swap this implementation
for a real HTTP call (httpx) against the provider's API when one is wired
into docker-compose.
"""
import hashlib


async def request_signature(contract_id: str, signer_email: str | None) -> str:
    """Returns a provider reference id for the signature request."""
    digest = hashlib.sha256(f"esign:{contract_id}:{signer_email or ''}".encode()).hexdigest()[:16]
    return f"esign-ref-{digest}"
