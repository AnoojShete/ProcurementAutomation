"""Unit tests for line-item categorization taxonomy (shared/taxonomy/line_item_categories.py)."""
import pytest
from shared.taxonomy.line_item_categories import categorize_line_item, LineItemCategory


class TestLineItemTaxonomy:
    @pytest.mark.parametrize(
        "description",
        [
            "Dell XPS 15 Laptop",
            "Apple MacBook Pro M3 16-inch",
            "27-inch 4K Monitor",
            "Cat6 Ethernet Cable 10ft",
            "USB-C Docking Station with dual HDMI",
            "Logitech MX Master 3S Wireless Mouse",
            "Mechanical Keyboard - Cherry MX Brown",
            "Network Switch 24-Port Gigabit Managed",
            "Cisco Edge Router ISR 4331",
            "PowerEdge R750 Rack Server 2U",
            "NVMe 2TB Solid State Drive SSD",
            "32GB DDR5 5600MHz RAM Memory Module",
            "Ergonomic Standing Desk",
            "Office Ergonomic Mesh Chair",
            "Noise Cancelling Over-Ear Headset",
            "Webcam 1080p with Privacy Shutter",
            "APC Smart-UPS 1500VA Battery Backup",
        ],
    )
    def test_known_hardware_terms(self, description: str):
        result = categorize_line_item(description)
        assert result == LineItemCategory.HARDWARE
        assert result == "hardware"

    @pytest.mark.parametrize(
        "description",
        [
            "Slack Enterprise Grid Monthly Subscription",
            "GitHub Enterprise Cloud 50 Seats",
            "Figma Organization Annual License",
            "JetBrains All Products Pack License Key",
            "Datadog Infrastructure Monitoring SaaS",
            "Snowflake Data Cloud Usage Credit",
            "AWS Cloud Services Compute Engine",
            "Microsoft 365 E5 Copilot License Renewal",
            "Zoom One Enterprise Video Conferencing",
            "Notion Team Plan Yearly Billing",
            "CrowdStrike Falcon Endpoint Security SaaS",
            "Atlassian Jira Software Cloud",
            "Salesforce Sales Cloud Enterprise Edition",
        ],
    )
    def test_known_software_terms(self, description: str):
        result = categorize_line_item(description)
        assert result == LineItemCategory.SOFTWARE
        assert result == "software"

    @pytest.mark.parametrize(
        "description",
        [
            "Custom implementation and setup",
            "Quarterly maintenance and support retainer",
            "Cloud migration architectural consulting",
            "Annual vendor SLA guarantee contract",
            "User training workshop session",
            "Courier delivery and shipping charges",
            "Freight handling and insurance fee",
            "Miscellaneous ad-hoc consulting",
            "Ambiguous unspecified item XYZ-9988",
            "General IT services and engineering assistance",
            "",
            "   ",
            "12345!@#$%",
            "Specialized technical audit services",
        ],
    )
    def test_ambiguous_or_unknown_terms_fallback_to_services(self, description: str):
        result = categorize_line_item(description)
        assert result == LineItemCategory.SERVICES
        assert result == "services"
        # CRITICAL requirement: fallback must NEVER be software
        assert result != "software"
        assert result != LineItemCategory.SOFTWARE
