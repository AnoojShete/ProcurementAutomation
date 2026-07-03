"""Basic procurement agent that uses only REST APIs."""
from __future__ import annotations

import os
from typing import Any

import requests


class ProcurementAgent:
    def __init__(self, base_url: str | None = None, timeout: int = 10) -> None:
        self.base_url = (base_url or os.getenv("API_BASE_URL") or "http://localhost:8000").rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None):
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    def create_vendor(self, payload: dict[str, Any]):
        return self._request("POST", "/vendors", payload)

    def get_vendor(self, vendor_id: int):
        return self._request("GET", f"/vendors/{vendor_id}")

    def list_vendors(self):
        return self._request("GET", "/vendors")

    def update_vendor(self, vendor_id: int, payload: dict[str, Any]):
        return self._request("PUT", f"/vendors/{vendor_id}", payload)

    def delete_vendor(self, vendor_id: int):
        return self._request("DELETE", f"/vendors/{vendor_id}")


def main() -> None:
    agent = ProcurementAgent()
    sample_vendor = {
        "company_name": "Northwind Supplies",
        "contact_person": "Ava Patel",
        "email": "ava.patel@northwind.example",
        "phone": "+1-555-0100",
        "gst_number": "GSTNORTHWIND001",
        "address": "100 Market Street, Suite 12",
        "status": "active",
    }

    created = agent.create_vendor(sample_vendor)
    print("Created vendor:", created)

    vendor_id = created["id"]
    print("Fetched vendor:", agent.get_vendor(vendor_id))
    print("Vendor list:", agent.list_vendors())
    print(
        "Updated vendor:",
        agent.update_vendor(vendor_id, {"phone": "+1-555-0199", "status": "verified"}),
    )
    print("Delete response:", agent.delete_vendor(vendor_id))


if __name__ == "__main__":
    main()
