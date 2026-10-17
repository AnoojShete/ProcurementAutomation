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

    def test_garbled_text_is_other_and_goes_to_review(self):
        # BR-3: no longer forced into "invoice".
        result = classify_document("asdkj 2109 !!! xoxo qqq")
        assert result.document_type == "other"
        assert result.needs_review

    def test_document_without_a_title_keyword_is_other(self):
        # a delivery note: "deliver to" alone isn't enough to call it a PO
        result = classify_document("DELIVERY NOTE\nDeliver to: Engineering\nItems: 5 laptops")
        assert result.document_type == "other"

    def test_titled_documents_keep_their_class(self):
        assert classify_document("TAX INVOICE\nInvoice Number: INV-1").document_type == "invoice"
        assert classify_document("PURCHASE ORDER\nPO Number: PO-7").document_type == "po"
        assert classify_document("QUOTATION\nValid until 30 Nov").document_type == "quote"
