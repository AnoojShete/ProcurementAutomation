"""Simple taxonomy for PO line items."""

import re

_SERVICES_KEYWORDS = [
    r"\b(?:consulting|consultant|implementation|migration|training|workshop|retainer|maintenance|support|shipping|freight|courier|delivery|fee|charges|audit|professional services|engineering assistance)\b"
]

_HARDWARE_KEYWORDS = [
    r"\b(?:laptop|desktop|server|monitor|display|keyboard|mouse|switch|router|cable|dock|docking station|gpu|macbook|thinkpad|workstation|printer|scanner|headset|webcam|camera|ssd|ram|memory|disk|drive|desk|chair|furniture|ups|battery|hardware)\b"
]

_SOFTWARE_KEYWORDS = [
    r"\b(?:license|licence|subscription|saas|software|seat|seats|cloud|aws|azure|gcp|office 365|m365|zoom|slack|notion|snowflake|crowdstrike|antivirus|os|jetbrains|intellij|github|gitlab|jira|confluence|salesforce|datadog|figma)\b"
]


class LineItemCategory:
    HARDWARE = "hardware"
    SOFTWARE = "software"
    SERVICES = "services"


def categorize_line_item(description: str) -> str:
    """Categorizes a PO line item based on its description.
    Defaults to 'services' if not clearly hardware or software.
    CRITICAL: Never default to 'software' to avoid unauthorized license creation.
    """
    desc = description.lower() if description else ""
    if not desc.strip():
        return LineItemCategory.SERVICES
    
    # Explicit service/consulting overrides software mentions (e.g. "Cloud migration consulting")
    for pattern in _SERVICES_KEYWORDS:
        if re.search(pattern, desc):
            return LineItemCategory.SERVICES

    for pattern in _SOFTWARE_KEYWORDS:
        if re.search(pattern, desc):
            return LineItemCategory.SOFTWARE
            
    for pattern in _HARDWARE_KEYWORDS:
        if re.search(pattern, desc):
            return LineItemCategory.HARDWARE
            
    return LineItemCategory.SERVICES
