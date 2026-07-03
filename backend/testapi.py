import requests
import random
import string
import time

BASE_URL = "http://localhost:8000"

def random_string(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))


def create_vendor():
    suffix = random_string()

    payload = {
        "company_name": f"Test Company {suffix}",
        "contact_person": "Anooj",
        "email": f"anooj{suffix.lower()}@gmail.com",
        "phone": "9876543210",
        "gst_number": f"GST{suffix}",
        "address": "Mumbai",
        "status": "active"
    }

    r = requests.post(f"{BASE_URL}/vendors", json=payload)

    print("\nCREATE")
    print(r.status_code)
    print(r.json())

    return r.json()["id"]


def get_vendor(vendor_id):
    r = requests.get(f"{BASE_URL}/vendors/{vendor_id}")

    print("\nGET")
    print(r.status_code)
    print(r.json())


def list_vendors():
    r = requests.get(f"{BASE_URL}/vendors")

    print("\nLIST")
    print(r.status_code)

    data = r.json()
    print(f"Total Vendors = {len(data)}")


def update_vendor(vendor_id):
    payload = {
        "status": "verified",
        "phone": "9999999999"
    }

    r = requests.put(
        f"{BASE_URL}/vendors/{vendor_id}",
        json=payload
    )

    print("\nUPDATE")
    print(r.status_code)
    print(r.json())


def delete_vendor(vendor_id):
    r = requests.delete(f"{BASE_URL}/vendors/{vendor_id}")

    print("\nDELETE")
    print(r.status_code)
    print(r.json())


def main():

    print("=" * 50)
    print(" PROCUREMENT API TEST ")
    print("=" * 50)

    vendor_id = create_vendor()

    time.sleep(1)

    get_vendor(vendor_id)

    time.sleep(1)

    list_vendors()

    time.sleep(1)

    update_vendor(vendor_id)

    time.sleep(1)

    delete_vendor(vendor_id)

    print("\nFinished Successfully")


if __name__ == "__main__":
    main()