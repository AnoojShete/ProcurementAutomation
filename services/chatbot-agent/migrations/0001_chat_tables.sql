CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS document_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(768),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_embeddings_cosine 
ON document_embeddings USING hnsw (embedding vector_cosine_ops);

-- RAG index (app/services/indexer.py): what each chunk came from, who may
-- see it, and a hash so only changed sources are re-embedded. Additive.
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS source_type VARCHAR(20);
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS section TEXT;
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS chunk_index INTEGER;
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS audience VARCHAR(10);
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS owner_email TEXT;
ALTER TABLE document_embeddings ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
CREATE INDEX IF NOT EXISTS idx_document_embeddings_source ON document_embeddings (source_type, document_id);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);