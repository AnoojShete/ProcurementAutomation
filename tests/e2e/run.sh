#!/usr/bin/env bash
# End-to-end test against the live, already-running stack (run ./run.sh
# first). Scripts the real flow through the gateway, exactly as a user
# would: log in as requester -> create a purchase request -> log in as
# approver -> approve it -> confirm a contract was generated -> send for
# signature -> simulate the e-sign webhook -> confirm the contract is
# signed and a risk score is attached -> confirm an email landed in
# Mailpit. Also checks ClamAV rejects an EICAR upload. This is the one test that proves the whole product works
# together, not just that each service passes its own unit tests.
set -euo pipefail
GATEWAY="${GATEWAY:-http://localhost:8080}"
MAILPIT="${MAILPIT:-http://localhost:8025}"
ESIGN_WEBHOOK_SECRET="${ESIGN_WEBHOOK_SECRET:-dev-esign-secret-change-me}"

pass=0
fail=0
step() { echo; echo "── $1"; }
ok() { echo "  ✓ $1"; pass=$((pass + 1)); }
bad() { echo "  ✗ $1"; fail=$((fail + 1)); }

# Usage: echo "$json_body" | json data.access_token
json() {
  python3 -c '
import json, sys
d = json.load(sys.stdin)
for key in sys.argv[1].split("."):
    d = d[key] if not key.isdigit() else d[int(key)]
print(d)
' "$1"
}

login() {
  curl -s -X POST "$GATEWAY/api/auth/login" -H "Content-Type: application/json" \
    -d "{\"email\":\"$1\",\"password\":\"DemoPass123!\"}" | json data.access_token
}

step "Log in as requester and admin"
REQUESTER_TOKEN=$(login requester@demo.example.com) && ok "requester token acquired" || { bad "requester login failed"; exit 1; }
APPROVER_TOKEN=$(login approver@demo.example.com) && ok "approver token acquired" || { bad "approver login failed"; exit 1; }
ADMIN_TOKEN=$(login admin@demo.example.com) && ok "admin token acquired" || { bad "admin login failed"; exit 1; }

step "ClamAV rejects a malware upload and accepts a clean one"
# EICAR is the industry-standard harmless antivirus test string.
EICAR_FILE=$(mktemp)
printf '%s' 'X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*' > "$EICAR_FILE"
EICAR_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY/api/documents/upload" \
  -H "Authorization: Bearer $REQUESTER_TOKEN" -F "file=@$EICAR_FILE;filename=eicar.pdf")
rm -f "$EICAR_FILE"
if [ "$EICAR_CODE" = "422" ]; then ok "EICAR upload rejected (422)"; else bad "EICAR upload not rejected (HTTP $EICAR_CODE)"; fi
CLEAN_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$GATEWAY/api/documents/upload" \
  -H "Authorization: Bearer $REQUESTER_TOKEN" \
  -F "file=@$(dirname "$0")/../../data/synthetic-invoices/01_po_delltechnologiesindi_PO-2026-00002.pdf")
if [ "$CLEAN_CODE" = "201" ] || [ "$CLEAN_CODE" = "200" ]; then ok "clean PDF accepted ($CLEAN_CODE)"; else bad "clean upload failed (HTTP $CLEAN_CODE)"; fi

step "Requester creates a manager-tier purchase request"
REQ=$(curl -s -X POST "$GATEWAY/api/requests/" -H "Authorization: Bearer $REQUESTER_TOKEN" -H "Content-Type: application/json" \
  -d '{"request_type":"saas","requested_by":"e2e@company.com","department":"Engineering","amount":2500,"currency":"INR"}')
REQUEST_ID=$(echo "$REQ" | json data.id)
STATUS=$(echo "$REQ" | json data.status)
if [ -n "$REQUEST_ID" ] && [ "$STATUS" = "pending_approval" ]; then ok "request $REQUEST_ID created (pending_approval)"; else bad "request creation failed: $REQ"; exit 1; fi

step "Approver approves it"
curl -s -X POST "$GATEWAY/api/requests/$REQUEST_ID/approve" -H "Authorization: Bearer $APPROVER_TOKEN" -H "Content-Type: application/json" \
  -d '{"decided_by":"dept_manager","comments":"e2e test approval"}' >/dev/null
# The decision is applied by signalling a Temporal workflow, processed
# asynchronously by the separate worker process — poll instead of trusting
# the approve call's immediate (pre-signal-processing) response.
APPROVED_STATUS="pending_approval"
for i in $(seq 1 20); do
  APPROVED_STATUS=$(curl -s "$GATEWAY/api/requests/$REQUEST_ID" -H "Authorization: Bearer $APPROVER_TOKEN" | json data.status)
  [ "$APPROVED_STATUS" = "approved" ] && break
  sleep 0.5
done
[ "$APPROVED_STATUS" = "approved" ] && ok "request approved" || { bad "approval did not settle to 'approved' (still: $APPROVED_STATUS)"; exit 1; }

step "Seed a vendor on the request (normally comes from document-vendor-agent's vendor.matched)"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-postgres}" -q <<SQL
INSERT INTO vendors (id, name, normalized_name) VALUES
  ('99999999-9999-9999-9999-999999999999', 'E2E Test Vendor Inc', 'e2e test vendor')
ON CONFLICT (id) DO NOTHING;
UPDATE purchase_requests SET vendor_id = '99999999-9999-9999-9999-999999999999' WHERE id = '$REQUEST_ID';
SQL
ok "vendor linked to request"

step "Admin generates a contract from the approved request"
GEN=$(curl -s -X POST "$GATEWAY/api/contracts/generate" -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d "{\"purchase_request_id\":\"$REQUEST_ID\",\"template_name\":\"saas_subscription\"}")
CONTRACT_ID=$(echo "$GEN" | json data.id)
[ -n "$CONTRACT_ID" ] && ok "contract $CONTRACT_ID generated" || { bad "contract generation failed: $GEN"; exit 1; }

step "Admin sends the contract for signature"
SEND=$(curl -s -X POST "$GATEWAY/api/contracts/$CONTRACT_ID/send-for-signature" -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" -d '{}')
SEND_STATUS=$(echo "$SEND" | json data.status)
[ "$SEND_STATUS" = "pending_signature" ] && ok "routed for signature" || { bad "send-for-signature failed: $SEND"; exit 1; }

step "Simulate the e-sign provider's signed-document webhook"
WEBHOOK_RESULT=$(python3 - "$CONTRACT_ID" "$ESIGN_WEBHOOK_SECRET" "$GATEWAY" <<'PYEOF'
import hmac, hashlib, json, sys, urllib.request
contract_id, secret, gateway = sys.argv[1], sys.argv[2], sys.argv[3]
body = {
    "provider_event_id": f"e2e-{contract_id}",
    "contract_id": contract_id,
    "signed_by": "vendor-signer@e2e-test-vendor.example.com",
    "signed_at": "2026-08-25T14:00:00+00:00",
}
canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
sig = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
payload = dict(body, signature=sig)
req = urllib.request.Request(f"{gateway}/api/webhooks/esign",
                              data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
PYEOF
)
WEBHOOK_STATUS=$(echo "$WEBHOOK_RESULT" | json data.status)
[ "$WEBHOOK_STATUS" = "signed" ] && ok "webhook processed, contract signed" || { bad "webhook failed: $WEBHOOK_RESULT"; exit 1; }

step "Confirm the contract shows signed"
FETCHED=$(curl -s "$GATEWAY/api/contracts/$CONTRACT_ID" -H "Authorization: Bearer $ADMIN_TOKEN")
FETCHED_STATUS=$(echo "$FETCHED" | json data.status)
[ "$FETCHED_STATUS" = "signed" ] && ok "GET /contracts/$CONTRACT_ID confirms signed" || bad "contract not showing signed: $FETCHED"

step "Recompute and confirm a risk score is attached to the vendor"
RISK=$(curl -s -X POST "$GATEWAY/api/vendors/99999999-9999-9999-9999-999999999999/risk/recompute" -H "Authorization: Bearer $ADMIN_TOKEN")
RISK_BAND=$(echo "$RISK" | json data.risk_band)
[ -n "$RISK_BAND" ] && ok "vendor risk scored: $RISK_BAND" || bad "risk scoring failed: $RISK"

step "Confirm a notification email landed in Mailpit"
sleep 2
MAILPIT_HIT=$(curl -s "$MAILPIT/api/v1/messages?limit=50" | python3 -c "
import json, sys
d = json.load(sys.stdin)
msgs = d.get('messages', [])
print('yes' if msgs else 'no')
")
if [ "$MAILPIT_HIT" = "yes" ]; then ok "Mailpit has recent messages (notification pipeline is alive)"; else bad "no messages found in Mailpit"; fi

step "Prompt 7: Mid-test Business Rule Mutation via Admin API"
PATCH_RULE=$(curl -s -X PATCH "$GATEWAY/api/admin/business-rules/license.anomaly_watch_threshold" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"new_value": 0.55, "justification": "E2E threshold mutation test without restart"}')
UPDATED_VAL=$(echo "$PATCH_RULE" | json data.current_value)
if [ "$UPDATED_VAL" = "0.55" ]; then ok "rule mutated mid-test to 0.55"; else bad "failed to mutate rule: $PATCH_RULE"; fi

step "Prompt 7: Verify History Audit Trail"
HIST=$(curl -s "$GATEWAY/api/admin/business-rules/history?rule_key=license.anomaly_watch_threshold" \
  -H "Authorization: Bearer $ADMIN_TOKEN")
HIST_JUSTIFICATION=$(python3 -c "
import json, sys
d = json.load(sys.stdin)
items = d.get('data', [])
print(items[0]['justification'] if items else '')
" <<< "$HIST")
if [ "$HIST_JUSTIFICATION" = "E2E threshold mutation test without restart" ]; then ok "history audit trail recorded"; else bad "history audit trail missing: $HIST"; fi

step "Prompt 7: Reset Rule to System Default"
RESET_RULE=$(curl -s -X POST "$GATEWAY/api/admin/business-rules/license.anomaly_watch_threshold/reset" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"justification": "Resetting e2e threshold mutation to default"}')
RESET_VAL=$(echo "$RESET_RULE" | json data.current_value)
if [ -n "$RESET_VAL" ]; then ok "rule reset successfully to $RESET_VAL"; else bad "failed to reset rule: $RESET_RULE"; fi

# The real 3-way invoice -> PO match (upload an invoice, pipeline finds the
# approved request, invoice.matched moves it to invoice_received) is covered
# end to end by tests/e2e/invoice_lifecycle.py. This script used to "test"
# it by setting the status with SQL, which could never fail.

echo
echo "=================================================================="
echo "  e2e: $pass passed, $fail failed"
echo "=================================================================="
[ "$fail" -eq 0 ]
