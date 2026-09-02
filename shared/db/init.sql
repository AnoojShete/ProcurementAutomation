-- Shared DB init for basic tables
CREATE TABLE IF NOT EXISTS vendors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  normalized_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_id UUID REFERENCES vendors(id),
  document_type TEXT,
  extracted JSONB,
  confidence JSONB,
  needs_review BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requested_by TEXT,
  department TEXT,
  amount NUMERIC,
  currency TEXT,
  status TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS licenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_id UUID REFERENCES vendors(id),
  app_name TEXT,
  total_seats INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS contracts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_request_id UUID REFERENCES purchase_requests(id),
  vendor_id UUID REFERENCES vendors(id),
  template TEXT,
  version INT DEFAULT 1,
  status TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_scores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  vendor_id UUID REFERENCES vendors(id),
  score NUMERIC,
  band TEXT,
  details JSONB,
  scored_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id UUID,
  entity_type TEXT,
  action TEXT,
  payload JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_webhook_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id TEXT UNIQUE NOT NULL,
  source TEXT NOT NULL,
  processed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS processed_kafka_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id UUID UNIQUE NOT NULL,
  topic TEXT NOT NULL,
  processed_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS system_settings (
  id INT PRIMARY KEY DEFAULT 1,
  live_verification_enabled BOOLEAN DEFAULT FALSE,
  enabled_by TEXT,
  enabled_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS api_quota_usage (
  api_name TEXT PRIMARY KEY,
  calls_used INT DEFAULT 0,
  calls_limit INT NOT NULL,
  limit_period TEXT NOT NULL,
  last_reset_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO api_quota_usage (api_name, calls_limit, limit_period) 
VALUES ('gstin_live', 20, 'total') 
ON CONFLICT (api_name) DO NOTHING;

INSERT INTO api_quota_usage (api_name, calls_limit, limit_period) 
VALUES ('opencorporates', 100, 'daily') 
ON CONFLICT (api_name) DO NOTHING;
