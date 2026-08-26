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
from decimal import Decimal
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
    
    The Redis lock is a SHORT-LIVED mutex (milliseconds) that guards
    the atomic check-and-decrement.  The actual "this stock is reserved
    pending approval" state lives in PostgreSQL (reserved_quantity column).
    
    Flow:
    1. Generate a unique UUID lock token (not the request_id — Issue 2)
    2. Acquire Redis lock on the SKU (NX + short TTL)
    3. Re-check availability inside the lock
    4. Decrement available_quantity, increment reserved_quantity in DB
    5. Commit the DB change
    6. Release the Redis lock immediately
    
    Args:
        db: Async database session.
        redis_client: Redis client for distributed locking.
        sku: SKU to reserve.
        request_id: ID of the request holding the reservation (for logging).
        quantity: Number of units to reserve.
        
    Returns:
        True if reservation succeeded, False if lock failed or
        insufficient stock.
    """
    lock = InventoryLock(redis_client, ttl=10)  # 10s safety TTL, released in ms
    lock_token = str(uuid.uuid4())  # Unique per acquisition (Issue 2)

    acquired = await lock.acquire(sku, lock_token)
    if not acquired:
        logger.warning(f"Could not acquire lock for SKU {sku} (request {request_id})")
        return False

    try:
        # Re-check availability inside the lock
        stmt = select(Inventory).where(Inventory.sku == sku)
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()

        if not item or item.available_quantity < quantity:
            avail = item.available_quantity if item else 0
            logger.info(
                f"Insufficient stock for {sku}: needed {quantity}, "
                f"available {avail} (request {request_id})"
            )
            return False

        # Atomic DB update — reservation state lives in PostgreSQL
        item.available_quantity -= quantity
        item.reserved_quantity += quantity
        await db.commit()
        logger.info(f"Reserved {quantity}x {sku} for request {request_id}")
        return True
    finally:
        # ALWAYS release the lock — even on failure
        await lock.release(sku, lock_token)


async def release_reservation(
    db: AsyncSession, redis_client, sku: str, request_id: str, quantity: int
) -> bool:
    """Release a previously held inventory reservation.
    
    Called when a request is rejected or fully approved (stock moves
    from reserved to allocated/shipped).
    
    Uses a fresh short-lived Redis lock to guard the atomic DB update,
    just like reserve_stock does.  The lock is NOT the reservation itself
    — the reservation lives in PostgreSQL (reserved_quantity column).
    
    Args:
        db: Async database session.
        redis_client: Redis client.
        sku: SKU to release.
        request_id: ID of the request that held the reservation (for logging).
        quantity: Number of units to release.
        
    Returns:
        True if release succeeded, False if lock contention or no stock to release.
    """
    lock = InventoryLock(redis_client, ttl=10)
    lock_token = str(uuid.uuid4())

    acquired = await lock.acquire(sku, lock_token)
    if not acquired:
        logger.warning(f"Could not acquire lock for SKU {sku} to release (request {request_id})")
        return False

    try:
        stmt = select(Inventory).where(Inventory.sku == sku)
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()

        if not item or item.reserved_quantity < quantity:
            logger.warning(
                f"Cannot release {quantity}x {sku}: reserved_quantity is "
                f"{item.reserved_quantity if item else 0} (request {request_id})"
            )
            return False

        item.reserved_quantity -= quantity
        item.available_quantity += quantity
        await db.commit()
        logger.info(f"Released reservation: {quantity}x {sku} for request {request_id}")
        return True
    finally:
        await lock.release(sku, lock_token)


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

    # Calculate amounts proportionally using Decimal (Issue 5)
    amount = original_request.amount  # Already Decimal from the ORM
    if total_requested > 0:
        ratio = Decimal(available_qty) / Decimal(total_requested)
        immediate_amount = (amount * ratio).quantize(Decimal("0.01"))
        backorder_amount = amount - immediate_amount
    else:
        immediate_amount = amount
        backorder_amount = Decimal("0")

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
            "cost_per_seat": str(lic.cost_per_seat) if lic.cost_per_seat else None,
            "period_end": lic.period_end.isoformat() if lic.period_end else None,
            "status": lic.status,
        })

    return license_data
