"""Two-party signing through Documenso: one row per signer of a contract.

The company's signatory signs first on the contract page, then the vendor
through an emailed link to the platform's vendor-signing page; both sign in
Documenso's embedded signing frame (esign_client.py, signing_service.py).

Revision ID: 0015
Revises: 0014
"""
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_signers (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            contract_id UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            party TEXT NOT NULL CHECK (party IN ('company', 'vendor')),
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            signing_order INTEGER NOT NULL,
            provider_recipient_id TEXT,
            -- Documenso's signing token for this recipient: it opens the
            -- signing frame, so it is only handed to the signer.
            provider_token TEXT,
            -- The vendor's emailed link carries a random token; only its
            -- SHA-256 is stored.
            link_token_sha256 VARCHAR(64) UNIQUE,
            link_expires_at TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'waiting'
                CHECK (status IN ('waiting', 'ready', 'signed', 'rejected')),
            signed_at TIMESTAMPTZ,
            rejection_reason TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (contract_id, party)
        );
        CREATE INDEX IF NOT EXISTS idx_contract_signers_contract ON contract_signers (contract_id);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS contract_signers")
