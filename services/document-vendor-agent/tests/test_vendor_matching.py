from app.services.vendor_matching import normalize_vendor_name


class TestVendorNameNormalization:
    def test_strips_corporate_suffix(self):
        assert normalize_vendor_name("Acme Corp, Inc.") == normalize_vendor_name("ACME CORP INC")

    def test_case_and_punctuation_insensitive(self):
        assert normalize_vendor_name("Acme IT Supplies, Inc.") == normalize_vendor_name("acme it supplies inc")

    def test_strips_multi_word_suffix(self):
        result = normalize_vendor_name("Beta Traders Private Limited")
        assert "private" not in result and "limited" not in result
        assert result == "beta traders"

    def test_collapses_whitespace(self):
        assert normalize_vendor_name("Acme    IT   Supplies") == "acme it supplies"

    def test_empty_input(self):
        assert normalize_vendor_name("") == ""
        assert normalize_vendor_name(None) == ""

    def test_distinct_vendors_stay_distinct(self):
        assert normalize_vendor_name("Acme Corp") != normalize_vendor_name("Globex Corp")
