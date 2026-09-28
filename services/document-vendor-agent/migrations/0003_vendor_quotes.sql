CREATE TABLE IF NOT EXISTS vendor_quotes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id),
  vendor_id UUID REFERENCES vendors(id),
  quote_number VARCHAR(255),
  valid_until DATE,
  total NUMERIC(14, 2),
  currency VARCHAR(10) DEFAULT 'INR',
  line_items JSONB,
  is_binding BOOLEAN DEFAULT false,
  raw_text TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
