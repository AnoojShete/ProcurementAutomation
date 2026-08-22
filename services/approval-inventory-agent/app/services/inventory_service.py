"""
Inventory management service for hardware stock and license tracking.

Handles:
- Hardware inventory queries with search/filter
- Stock availability checks
- Redis-locked reservation (prevents double-booking)
- Backorder splitting for partial fulfillment
- License inventory with usage aggregations
"""
import uuid
import logging
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from app.models import Inventory, License, LicenseUsage, PurchaseRequest
from app.services.redis_lock import InventoryLock

logger = logging.getLogger(__name__)


async def get_all_inventory(
    db: AsyncSession,
    category: Optional[str] = None,
    search: Optional[str] = None
) -> List[Inventory]:
    """Query hardware inventory with optional category filter and text search.
    
    Args:
        db: Async database session.
        category: Filter by category (e.g., 'laptop', 'monitor').
        search: Text search across name and SKU fields.
        
    Returns:
        List of matching Inventory items.
    """
    stmt = select(Inventory)
    if category:
        stmt = stmt.where(Inventory.category == category)
    if search:
        stmt = stmt.where(or_(
            Inventory.name.ilike(f"%{search}%"),
            Inventory.sku.ilike(f"%{search}%")
        ))
    stmt = stmt.order_by(Inventory.category, Inventory.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def check_availability(db: AsyncSession, sku: str, quantity: int) -> bool:
    """Check if sufficient stock is available for a given SKU.
    
    Args:
        db: Async database session.
        sku: The stock keeping unit identifier.
        quantity: Number of units requested.
        
    Returns:
        True if available_quantity >= requested quantity.
    """
    stmt = select(Inventory).where(Inventory.sku == sku)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        return False
    return item.available_quantity >= quantity


async def reserve_stock(
    db: AsyncSession, redis_client, sku: str, request_id: str, quantity: int
) -> bool:
    """Reserve inventory stock using a Redis distributed lock.
    
    The lock prevents two concurrent purchase requests from
    double-reserving the same stock. Flow:
    1. Acquire Redis lock on the SKU (NX + TTL)
    2. Re-check availability inside the lock
    3. Decrement available, increment reserved
    4. Keep the lock until the request is decided
    
    Args:
        db: Async database session.
        redis_client: Redis client for distributed locking.
        sku: SKU to reserve.
        request_id: ID of the request holding the reservation.
        quantity: Number of units to reserve.
        
    Returns:
        True if reservation succeeded, False if lock failed or
        insufficient stock.
    """
    lock = InventoryLock(redis_client)
    acquired = await lock.acquire(sku, request_id)
    if not acquired:
        logger.warning(f"Could not acquire lock for SKU {sku} (request {request_id})")
        return False

    # Re-check availability inside the lock
    stmt = select(Inventory).where(Inventory.sku == sku)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if item and item.available_quantity >= quantity:
        item.available_quantity -= quantity
        item.reserved_quantity += quantity
        await db.commit()
        logger.info(f"Reserved {quantity}x {sku} for request {request_id}")
        return True

    # Not enough stock — release the lock
    await lock.release(sku, request_id)
    logger.info(f"Insufficient stock for {sku}: needed {quantity}, available {item.available_quantity if item else 0}")
    return False


async def release_reservation(
    db: AsyncSession, redis_client, sku: str, request_id: str, quantity: int
) -> bool:
    """Release a previously held inventory reservation.
    
    Called when a request is rejected or fully approved (stock moves
    from reserved to allocated/shipped).
    
    Args:
        db: Async database session.
        redis_client: Redis client.
        sku: SKU to release.
        request_id: ID of the request that held the reservation.
        quantity: Number of units to release.
        
    Returns:
        True if release succeeded.
    """
    lock = InventoryLock(redis_client)
    released = await lock.release(sku, request_id)
    if not released:
        logger.warning(f"Could not release lock for SKU {sku} (request {request_id})")
        return False

    stmt = select(Inventory).where(Inventory.sku == sku)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if item and item.reserved_quantity >= quantity:
        item.reserved_quantity -= quantity
        item.available_quantity += quantity
        await db.commit()
        logger.info(f"Released reservation: {quantity}x {sku} for request {request_id}")
        return True

    return False


async def split_backorder(
    db: AsyncSession, original_request: PurchaseRequest, available_qty: int
) -> tuple:
    """Split a request into immediately-fulfillable and backordered portions.
    
    When a hardware purchase request exceeds available stock, this creates
    two child requests:
    1. An immediate portion for the available quantity
    2. A backordered portion for the remainder
    
    The original request becomes the parent and is marked as split.
    
    Args:
        db: Async database session.
        original_request: The original purchase request to split.
        available_qty: Number of units currently available.
        
    Returns:
        Tuple of (immediate_request, backordered_request).
    """
    items = original_request.items or []
    if not items:
        return None, None

    # Calculate total requested quantity
    total_requested = sum(item.get("quantity", 0) for item in items)
    if available_qty >= total_requested:
        return original_request, None  # No split needed

    # Create the immediate portion
    immediate_items = []
    backorder_items = []
    remaining_available = available_qty

    for item in items:
        qty = item.get("quantity", 0)
        if remaining_available >= qty:
            immediate_items.append(item.copy())
            remaining_available -= qty
        elif remaining_available > 0:
            # Split this item
            immediate_item = item.copy()
            immediate_item["quantity"] = remaining_available
            immediate_items.append(immediate_item)

            backorder_item = item.copy()
            backorder_item["quantity"] = qty - remaining_available
            backorder_items.append(backorder_item)
            remaining_available = 0
        else:
            backorder_items.append(item.copy())

    # Calculate amounts proportionally
    if total_requested > 0:
        immediate_amount = float(original_request.amount) * (available_qty / total_requested)
        backorder_amount = float(original_request.amount) - immediate_amount
    else:
        immediate_amount = float(original_request.amount)
        backorder_amount = 0

    # Create immediate child request
    immediate_req = PurchaseRequest(
        id=str(uuid.uuid4()),
        request_type=original_request.request_type,
        requested_by=original_request.requested_by,
        department=original_request.department,
        vendor_id=original_request.vendor_id,
        amount=immediate_amount,
        currency=original_request.currency,
        spend_tier=original_request.spend_tier,
        approval_chain=original_request.approval_chain,
        status="pending_approval",
        items=immediate_items,
        backorder_parent_id=original_request.id,
        is_backordered=False,
    )
    db.add(immediate_req)

    # Create backordered child request
    backorder_req = PurchaseRequest(
        id=str(uuid.uuid4()),
        request_type=original_request.request_type,
        requested_by=original_request.requested_by,
        department=original_request.department,
        vendor_id=original_request.vendor_id,
        amount=backorder_amount,
        currency=original_request.currency,
        spend_tier=original_request.spend_tier,
        approval_chain=original_request.approval_chain,
        status="backordered",
        items=backorder_items,
        backorder_parent_id=original_request.id,
        is_backordered=True,
        comments=f"Backordered: {total_requested - available_qty} units pending stock",
    )
    db.add(backorder_req)

    # Mark original as split
    original_request.status = "split"
    original_request.comments = (
        f"Split into immediate ({available_qty} units) "
        f"and backordered ({total_requested - available_qty} units)"
    )
    await db.commit()

    logger.info(
        f"Split request {original_request.id}: "
        f"immediate={immediate_req.id} ({available_qty} units), "
        f"backordered={backorder_req.id} ({total_requested - available_qty} units)"
    )

    return immediate_req, backorder_req


async def get_license_inventory(db: AsyncSession) -> list[dict]:
    """Query all licenses with aggregated usage statistics.
    
    For each license, computes the number of active users in each
    time window by querying the license_usage table.
    
    Returns:
        List of dicts with license info + usage aggregations.
    """
    stmt = select(License).where(License.status == "active")
    result = await db.execute(stmt)
    licenses = result.scalars().all()

    license_data = []
    for lic in licenses:
        # Count active users per time window
        active_30d = (await db.execute(
            select(func.count()).select_from(LicenseUsage)
            .where(LicenseUsage.license_id == lic.id)
            .where(LicenseUsage.login_count_30d > 0)
        )).scalar() or 0

        active_60d = (await db.execute(
            select(func.count()).select_from(LicenseUsage)
            .where(LicenseUsage.license_id == lic.id)
            .where(LicenseUsage.login_count_60d > 0)
        )).scalar() or 0

        active_90d = (await db.execute(
            select(func.count()).select_from(LicenseUsage)
            .where(LicenseUsage.license_id == lic.id)
            .where(LicenseUsage.login_count_90d > 0)
        )).scalar() or 0

        utilisation = active_30d / lic.total_seats if lic.total_seats > 0 else 0.0

        license_data.append({
            "id": lic.id,
            "vendor_id": lic.vendor_id,
            "app_name": lic.app_name,
            "total_seats": lic.total_seats,
            "active_seats_30d": active_30d,
            "active_seats_60d": active_60d,
            "active_seats_90d": active_90d,
            "utilisation_score": round(utilisation, 4),
            "cost_per_seat": float(lic.cost_per_seat) if lic.cost_per_seat else None,
            "period_end": lic.period_end.isoformat() if lic.period_end else None,
            "status": lic.status,
        })

    return license_data
