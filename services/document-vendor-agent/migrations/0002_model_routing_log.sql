CREATE TABLE IF NOT EXISTS model_routing_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id),
    route_name VARCHAR(50) NOT NULL,
    model_used VARCHAR(50) NOT NULL,
    fallback_triggered BOOLEAN DEFAULT false,
    fallback_reason VARCHAR(50),
    confidence NUMERIC(4,3),
    duration_ms NUMERIC(10,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
