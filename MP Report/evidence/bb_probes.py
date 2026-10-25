"""Live black-box probes through the gateway, for the report's Table 5.x."""
import json, sys, urllib.request, urllib.error, uuid

BASE = "http://localhost:8080/api"


def call(method, path, token=None, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def login(email, pw="DemoPass123!"):
    s, b = call("POST", "/auth/login", body={"email": email, "password": pw})
    return json.loads(b)["data"]["access_token"] if s == 200 else None


req = login("requester@demo.example.com")
appr = login("approver@demo.example.com")
fin = login("finance@demo.example.com")
foreign_contract = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
rid = str(uuid.uuid4())

probes = [
    ("No token on a protected endpoint", "GET", "/requests/", None, None, None),
    ("Requester verifies a bank-detail change", "POST", f"/vendors/{rid}/verify-payment-change", req, {}, None),
    ("Requester opens the approver inbox", "GET", "/inbox/", req, None, None),
    ("Approver opens the approver inbox", "GET", "/inbox/", appr, None, None),
    ("Webhook with a wrong HMAC signature", "POST", "/webhooks/esign", None,
     {"provider_event_id": str(uuid.uuid4()), "contract_id": rid, "signed_by": "x@y.z",
      "signed_at": "2026-10-17T10:00:00+00:00", "signature": "deadbeef"}, None),
    ("Malformed UUID in a path", "GET", "/vendors/2.1/risk", fin, None, None),
    ("NaN amount on a purchase request", "POST", "/requests/", req, None,
     b'{"request_type":"license","department":"IT","amount":NaN}'),
    ("Negative item quantity", "POST", "/requests/", req,
     {"request_type": "hardware", "department": "IT", "amount": 100,
      "items": [{"sku": "LAP-001", "quantity": -3}]}, None),
    ("Requester downloads another user's contract", "GET", f"/contracts/{foreign_contract}/document", req, None, None),
    ("Wrong password vs unknown e-mail", "POST", "/auth/login", None,
     {"email": "requester@demo.example.com", "password": "WrongPass123!x"}, None),
    ("", "POST", "/auth/login", None, {"email": "nobody-xyz@demo.example.com", "password": "WrongPass123!x"}, None),
]
for name, m, p, t, body, raw in probes:
    s, b = call(m, p, t, body, raw)
    print(f"{s}\t{name}\t{m} {p}\t{b[:110]}")
