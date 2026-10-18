-- Foreign-currency documents: the amount in the base currency (INR) and the
-- exchange rate used, captured once when the document is processed so the
-- converted value never moves with later rate changes. `total`/`currency`
-- stay as printed on the document. For INR documents rate = 1.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS total_inr NUMERIC(14, 2);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS fx_rate NUMERIC(18, 8);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS fx_rate_date DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS fx_source TEXT
