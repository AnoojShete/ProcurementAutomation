"""
Inventory API endpoints for the Approval & Inventory Intelligence Agent.

Provides hardware inventory and license inventory views with
search and filtering capabilities.
"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas import DataResponse, InventoryItemResponse, LicenseResponse
from app.services.inventory_service import get_all_inventory, get_license_inventory

router = APIRouter()


@router.get("/", response_model=DataResponse)
async def list_inventory(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all hardware inventory and software license inventory.
    
    Query Parameters:
        category: Filter hardware by category (e.g., 'laptop', 'monitor')
        search: Text search across hardware name and SKU
        
    Returns:
        DataResponse with 'hardware' (list of InventoryItemResponse)
        and 'licenses' (list of LicenseResponse).
    """
    # Hardware inventory from the inventory table
    hw_inv = await get_all_inventory(db, category, search)
    
    # License inventory with usage aggregations from licenses + license_usage tables
    lic_inv = await get_license_inventory(db)

    return DataResponse(
        data={
            "hardware": [
                InventoryItemResponse.model_validate(item) for item in hw_inv
            ],
            "licenses": [
                LicenseResponse(**lic) for lic in lic_inv
            ],
        },
        meta={
            "hardware_count": len(hw_inv),
            "license_count": len(lic_inv),
        }
    )
