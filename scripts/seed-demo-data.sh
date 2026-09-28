#!/usr/bin/env bash
# Seeds one demo vendor, one approved purchase request, five SaaS licenses
# and four hardware SKUs directly into
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

INSERT INTO purchase_requests (id, requested_by, department, amount, currency, status, request_type)
VALUES ('$DEMO_REQUEST_ID', 'jane@company.com', 'Engineering', 4500, 'INR', 'approved', 'hardware')
ON CONFLICT (id) DO NOTHING;

UPDATE purchase_requests
SET vendor_id = '$DEMO_VENDOR_ID',
    items = '[{"description":"Laptops","quantity":5,"unit_price":900}]'::jsonb
WHERE id = '$DEMO_REQUEST_ID';

-- Software licenses. app_name must match data/synthetic-sso-logs/ (each app
-- has ~40-45 active users there), so seat counts are chosen to give the
-- Licenses page a spread: two right-sized, one mildly and two heavily
-- over-provisioned (reclaim candidates).
INSERT INTO licenses (id, vendor_id, app_name, total_seats, assigned_seats, cost_per_seat, currency, period_start, period_end, status) VALUES
  ('33333333-0000-0000-0000-000000000001', '$DEMO_VENDOR_ID', 'Microsoft 365 E3',            50,  48, 2100.00, 'INR', '2026-04-01', '2027-03-31', 'active'),
  ('33333333-0000-0000-0000-000000000002', '$DEMO_VENDOR_ID', 'Slack Enterprise',            45,  44, 1250.00, 'INR', '2026-04-01', '2027-03-31', 'active'),
  ('33333333-0000-0000-0000-000000000003', '$DEMO_VENDOR_ID', 'Docker Pro',                  60,  55,  750.00, 'INR', '2026-04-01', '2027-03-31', 'active'),
  ('33333333-0000-0000-0000-000000000004', '$DEMO_VENDOR_ID', 'JetBrains All Products Pack', 120, 110, 2400.00, 'INR', '2026-04-01', '2027-03-31', 'active'),
  ('33333333-0000-0000-0000-000000000005', '$DEMO_VENDOR_ID', 'Notion Team',                 200, 180,  800.00, 'INR', '2026-04-01', '2027-03-31', 'active')
ON CONFLICT (id) DO NOTHING;

-- Hardware stock for the Inventory page and reservation-lock demo.
INSERT INTO inventory (id, sku, name, category, total_quantity, available_quantity, reserved_quantity, unit_cost, currency, location) VALUES
  ('44444444-0000-0000-0000-000000000001', 'LAPTOP-DELL-5540', 'Dell Latitude 5540',      'laptop',    20, 12, 0, 85000.00, 'INR', 'Pune HQ'),
  ('44444444-0000-0000-0000-000000000002', 'LAPTOP-MBP-14',    'MacBook Pro 14 (M3)',     'laptop',     8,  2, 0, 169900.00, 'INR', 'Pune HQ'),
  ('44444444-0000-0000-0000-000000000003', 'MON-DELL-U2723',   'Dell UltraSharp 27 U2723', 'monitor',  30, 25, 0, 42000.00, 'INR', 'Pune HQ'),
  ('44444444-0000-0000-0000-000000000004', 'DOCK-DELL-WD19',   'Dell WD19S Dock',         'accessory', 25,  0, 0, 18500.00, 'INR', 'Mumbai Office')
ON CONFLICT (id) DO NOTHING;
SQL

# The usage scanner ingests SSO logs and scores licenses on startup (then
# hourly) — restart it so the newly seeded licenses get scored now.
echo "Restarting approval-inventory-agent so the usage scanner scores the new licenses..."
docker compose restart approval-inventory-agent >/dev/null

echo
echo "Seeded:"
echo "  vendor_id:  $DEMO_VENDOR_ID  (Acme IT Supplies Inc)"
echo "  request_id: $DEMO_REQUEST_ID (approved, INR 4500, Engineering)"
echo "  licenses:   5 SaaS licenses (Licenses page — anomaly scores appear within ~1 min)"
echo "  inventory:  4 hardware SKUs (one out of stock, to show backorder split)"
echo
echo "Try in the frontend (Contracts & Vendor Risk tab):"
echo "  - Generate a contract from purchase request $DEMO_REQUEST_ID"
echo "  - Look up vendor risk for $DEMO_VENDOR_ID"
