import asyncio
import json
from sqlalchemy import select, text
from app.database import async_session_factory
from app.models import Vendor, RiskScore, RiskScoreRuleResult
from app.services import risk_service

VENDOR_ID = "e4b1673e-3b1c-4fdc-82d3-fa86c90feba5"


async def verify():
    async with async_session_factory() as db:
        vendor = await db.get(Vendor, VENDOR_ID)
        print("--- 1. Target Vendor Profile ---")
        print(f"ID: {vendor.id}")
        print(f"Name: {vendor.name}")
        print(f"Website: {vendor.website}")
        print(f"GSTIN: {vendor.gstin}")
        print(f"Country: {vendor.country}")
        print(f"Inherent Tier: {vendor.inherent_tier}")
        print(f"Onboarded by: {vendor.onboarded_by}")

        print("\n--- 2. Running Scorecard Evaluation ---")
        score_row = await risk_service.score_vendor(
            db=db,
            kafka_producer=None,
            vendor_id=VENDOR_ID,
            trigger_type="manual_verification",
            force_fresh_collect=True,
        )
        print(f"Score ID: {score_row.id}")
        print(f"Total Points: {score_row.total_points}")
        print(f"Final Band: {score_row.final_band}")
        print(f"Rating Status: {score_row.rating_status}")

        print("\n--- 3. Explanation & Honest Display ---")
        expl = score_row.explanation or {}
        print(f"Arithmetic line: {expl.get('arithmetic_line')}")
        print(f"Safety notice: {expl.get('safety_notice')}")
        print(f"Attribution: {expl.get('attribution')}")

        print("\n--- 4. Groups & Checks Formatting ---")
        for g in expl.get("groups", []):
            print(f"Group: {g.get('label')} -> Header: {g.get('header')}")
            for s in g.get("sentences", []):
                print(f"  * {s}")

        # Query rule results from RiskScoreRuleResult table
        rule_results = (
            await db.scalars(
                select(RiskScoreRuleResult)
                .where(RiskScoreRuleResult.score_id == score_row.id)
                .order_by(RiskScoreRuleResult.order_index)
            )
        ).all()

        # Check breach rule result
        rr_breach = next((r for r in rule_results if r.signal_key == "breach"), None)
        print(f"\n--- 5. Breach Signal Result ---")
        print(f"Rule ID: {rr_breach.rule_id if rr_breach else 'None'}")
        print(f"Points: {rr_breach.points if rr_breach else 'None'}")
        print(f"Potential: {rr_breach.potential_points if rr_breach else 'None'}")
        print(f"Status: {rr_breach.status if rr_breach else 'None'}")
        print(f"Reason: {rr_breach.reason_text if rr_breach else 'None'}")

        # Check GST rule result
        rr_gst = next((r for r in rule_results if r.signal_key == "gst"), None)
        print(f"\n--- 6. GST Signal Result ---")
        print(f"Rule ID: {rr_gst.rule_id if rr_gst else 'None'}")
        print(f"Points: {rr_gst.points if rr_gst else 'None'}")
        print(f"Status: {rr_gst.status if rr_gst else 'None'}")
        print(f"Reason: {rr_gst.reason_text if rr_gst else 'None'}")

        # Check Sanctions rule result
        rr_sanctions = next((r for r in rule_results if r.signal_key == "sanctions"), None)
        print(f"\n--- 7. Sanctions Signal Result ---")
        print(f"Rule ID: {rr_sanctions.rule_id if rr_sanctions else 'None'}")
        print(f"Points: {rr_sanctions.points if rr_sanctions else 'None'}")
        print(f"Status: {rr_sanctions.status if rr_sanctions else 'None'}")
        print(f"Reason: {rr_sanctions.reason_text if rr_sanctions else 'None'}")

        # Check Web rule result
        rr_web = next((r for r in rule_results if r.signal_key == "web"), None)
        print(f"\n--- 8. Web Signal Result ---")
        print(f"Rule ID: {rr_web.rule_id if rr_web else 'None'}")
        print(f"Points: {rr_web.points if rr_web else 'None'}")
        print(f"Status: {rr_web.status if rr_web else 'None'}")
        print(f"Reason: {rr_web.reason_text if rr_web else 'None'}")

        # Check Cert rule result
        rr_cert = next((r for r in rule_results if r.signal_key == "certification"), None)
        print(f"\n--- 9. Certification Signal Result ---")
        print(f"Rule ID: {rr_cert.rule_id if rr_cert else 'None'}")
        print(f"Points: {rr_cert.points if rr_cert else 'None'}")
        print(f"Status: {rr_cert.status if rr_cert else 'None'}")
        print(f"Reason: {rr_cert.reason_text if rr_cert else 'None'}")

        print("\nTarget vendor verification COMPLETED successfully!")


if __name__ == "__main__":
    asyncio.run(verify())
