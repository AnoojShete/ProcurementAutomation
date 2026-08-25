from app.services.classification import classify_document


class TestClassification:
    def test_invoice_classified_correctly(self):
        text = "TAX INVOICE\nInvoice Number: INV-1001\nInvoice Date: 2026-01-05\nBill To: Acme Corp\nAmount Due: 4500.00"
        result = classify_document(text)
        assert result.document_type == "invoice"
        assert result.confidence > 0.5

    def test_purchase_order_classified_correctly(self):
        text = "PURCHASE ORDER\nPO Number: PO-2002\nPO Date: 2026-01-05\nShip To: Warehouse 3\nAuthorized By: J. Smith"
        result = classify_document(text)
        assert result.document_type == "po"

    def test_quote_classified_correctly(self):
        text = "QUOTATION\nQuote Number: QT-3003\nValid Until: 2026-02-01\nThis is a price quote for IT hardware."
        result = classify_document(text)
        assert result.document_type == "quote"

    def test_garbled_text_defaults_to_low_confidence_invoice(self):
        result = classify_document("asdkj 2109 !!! xoxo qqq")
        assert result.document_type == "invoice"
        assert result.confidence <= 0.3
