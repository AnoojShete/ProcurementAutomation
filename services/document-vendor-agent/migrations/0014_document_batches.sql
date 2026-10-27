-- Prompt 11: Document batches, batch files, and document references.

CREATE TABLE IF NOT EXISTS document_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
    total_files INT NOT NULL DEFAULT 0,
    processed_files INT NOT NULL DEFAULT 0,
    failed_files INT NOT NULL DEFAULT 0,
    cancelled_files INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    metadata JSONB
);

CREATE INDEX IF NOT EXISTS idx_document_batches_user ON document_batches (user_id);
CREATE INDEX IF NOT EXISTS idx_document_batches_status ON document_batches (status);

CREATE TABLE IF NOT EXISTS document_batch_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES document_batches(id) ON DELETE CASCADE,
    client_file_id TEXT NOT NULL,
    client_relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    sha256_hash TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
    error_code TEXT,
    error_detail TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_batch_client_file UNIQUE (batch_id, client_file_id)
);

CREATE INDEX IF NOT EXISTS idx_batch_files_batch ON document_batch_files (batch_id);
CREATE INDEX IF NOT EXISTS idx_batch_files_status ON document_batch_files (status);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS batch_id UUID REFERENCES document_batches(id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS client_file_id TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS client_relative_path TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS sha256_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_documents_batch_id ON documents (batch_id);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents (sha256_hash);
