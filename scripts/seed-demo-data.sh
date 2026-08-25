#!/usr/bin/env bash
# Seeds one demo vendor + one approved purchase request directly into
# Postgres, so there's something to click through in the frontend (contract
# generation, vendor risk lookup) immediately after `./run.sh`, without
# first uploading a document or waiting on the approval chain.
#
# Idempotent — reruns safely (ON CONFLICT DO NOTHING keyed on fixed ids).
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

POSTGRES_USER="${POSTGRES_USER:-postgres}"
DEMO_VENDOR_ID="11111111-1111-1111-1111-111111111111"
DEMO_REQUEST_ID="22222222-2222-2222-2222-222222222222"

echo "Seeding demo vendor + approved purchase request..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" <<SQL
INSERT INTO vendors (id, name, normalized_name)
VALUES ('$DEMO_VENDOR_ID', 'Acme IT Supplies Inc', 'acme it supplies')
ON CONFLICT (id) DO NOTHING;

INSERT INTO purchase_requests (id, requested_by, department, amount, currency, status)
VALUES ('$DEMO_REQUEST_ID', 'jane@company.com', 'Engineering', 4500, 'INR', 'approved')
ON CONFLICT (id) DO NOTHING;

UPDATE purchase_requests
SET vendor_id = '$DEMO_VENDOR_ID',
    items = '[{"description":"Laptops","quantity":5,"unit_price":900}]'::jsonb
WHERE id = '$DEMO_REQUEST_ID';
SQL

echo
echo "Seeded:"
echo "  vendor_id:  $DEMO_VENDOR_ID  (Acme IT Supplies Inc)"
echo "  request_id: $DEMO_REQUEST_ID (approved, INR 4500, Engineering)"
echo
echo "Try in the frontend (Contracts & Vendor Risk tab):"
echo "  - Generate a contract from purchase request $DEMO_REQUEST_ID"
echo "  - Look up vendor risk for $DEMO_VENDOR_ID"
