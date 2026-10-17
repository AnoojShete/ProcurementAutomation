import csv
import os
import random

# Note: The following Hugging Face datasets can be loaded via `datasets` for more real-world documents:
# - AyoubChLin/CompanyDocuments
# - AyoubChLin/northwind_PurchaseOrders
# - mychen76/invoices-and-receipts_ocr_v1
# - Voxel51/high-quality-invoice-images-for-ocr
# - priyank-m/SROIE_2019_text_recognition

def generate_invoice():
    amounts = [100.0, 250.5, 99.99, 1000.0, 5000.0, 42.0, 999.0, 123.45]
    companies = ["Acme Corp", "Globex", "Initech", "Umbrella Corp", "Stark Industries", "Wayne Enterprises"]
    terms = ["Net 30", "Due on Receipt", "Net 15", "Net 60"]
    text = f"TAX INVOICE\n\nInvoice Number: INV-{random.randint(1000, 9999)}\n"
    text += f"Invoice Date: 2026-09-23\nBill To: {random.choice(companies)}\n"
    text += f"Amount Due: ${random.choice(amounts)}\n"
    text += f"Terms: {random.choice(terms)}\n"
    text += "Please remit to our bank account. Remittance address below."
    return text

def generate_po():
    items = ["Laptops", "Office Chairs", "Server Racks", "Coffee Beans", "Monitors", "Keyboards"]
    companies = ["Acme Corp", "Globex", "Initech", "Umbrella Corp", "Stark Industries", "Wayne Enterprises"]
    text = f"PURCHASE ORDER\n\nPO Number: PO-{random.randint(10000, 99999)}\n"
    text += f"PO Date: 2026-09-22\nVendor: {random.choice(companies)}\n"
    text += f"Ship To: HQ Warehouse\n"
    text += f"Deliver To: Receiving Dock 4\n"
    text += f"Authorized By: Procurement Dept\n"
    text += f"Description: {random.choice(items)}\n"
    text += f"Total: ${random.randint(50, 5000)}\n"
    return text

def generate_quote():
    items = ["Software License", "Consulting Hours", "Cloud Storage", "Maintenance", "Security Audit"]
    companies = ["Acme Corp", "Globex", "Initech", "Umbrella Corp", "Stark Industries", "Wayne Enterprises"]
    text = f"PRICE QUOTE / ESTIMATE\n\nQuote Number: QT-{random.randint(100, 999)}\n"
    text += f"Date: 2026-09-20\nPrepared For: {random.choice(companies)}\n"
    text += f"Valid Until: 2026-10-20\n"
    text += f"Proposal for {random.choice(items)}.\n"
    text += f"Estimated Cost: ${random.randint(100, 10000)}\n"
    text += f"This quotation is subject to our standard terms."
    return text

def main():
    out_dir = r"d:\ProcurementAutomation\data\synthetic-classification"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "classification_training_data.csv")
    
    samples = []
    # Generate 35 of each to get 105 total (90+)
    for _ in range(35):
        samples.append((generate_invoice(), "invoice"))
        samples.append((generate_po(), "po"))
        samples.append((generate_quote(), "quote"))
        
    random.shuffle(samples)
    
    with open(out_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "label"])
        for text, label in samples:
            writer.writerow([text, label])
            
    print(f"Generated {len(samples)} synthetic samples to {out_path}")

if __name__ == "__main__":
    main()
