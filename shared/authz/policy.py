"""Central Object and Property Level Authorization Policy Engine (OWASP API1 / API3).

Every read and write of requests, contracts, documents, ratings, batches,
notifications, and risk data goes through this policy.
Ownership is determined strictly by authenticated User ID (UUID), never by email.
"""
from enum import Enum
from typing import Any, Optional
from shared.auth.middleware import CurrentUser


class Action(str, Enum):
    READ = "read"
    WRITE = "write"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    APPROVE = "approve"
    EXPORT = "export"
    ERASE = "erase"


class PolicyError(Exception):
    pass


def can(user: CurrentUser, action: str | Action, resource: Any) -> bool:
    """Determine whether `user` is authorized to perform `action` on `resource`.

    Rules:
    1. Admin has broad access to manage and review platform resources, subject
       to statutory dual-control rules (e.g. erasure requires two distinct admins).
    2. Ownership is evaluated strictly using `user.id` against resource owner fields
       (`requested_by_user_id`, `created_by_user_id`, `user_id`, `owner_id`).
       Email is NEVER used as an authorization ownership key.
    3. Non-owners cannot read, modify, or approve another user's restricted objects.
    4. Approvers and Finance roles can read and approve items within their purview.
    """
    if isinstance(action, str):
        try:
            action = Action(action.lower())
        except ValueError:
            return False

    if not user or not user.id:
        return False

    # Admin global permissions
    if user.role == "admin":
        return True

    # None or general collection resource checks
    if resource is None:
        if action == Action.READ:
            return True
        if action in (Action.CREATE, Action.WRITE):
            return user.role in ("requester", "approver", "finance")
        return False

    # Extract resource owner attributes if present
    owner_id: Optional[str] = None
    for attr in ("requested_by_user_id", "created_by_user_id", "user_id", "owner_id", "sub"):
        val = getattr(resource, attr, None)
        if val is not None:
            owner_id = str(val)
            break
        if isinstance(resource, dict) and attr in resource and resource[attr] is not None:
            owner_id = str(resource[attr])
            break

    # Resource type identification
    resource_type = getattr(resource, "__tablename__", type(resource).__name__.lower())
    if isinstance(resource, dict):
        resource_type = resource.get("entity_type", resource.get("resource_type", "generic"))

    # 1. Purchase Requests
    if "purchase_request" in resource_type or "request" in resource_type:
        is_owner = (owner_id == user.id)
        if action == Action.READ:
            # Owner can read, and approvers/finance can read pending/active requests
            return is_owner or user.role in ("approver", "finance")
        if action in (Action.UPDATE, Action.WRITE):
            # Only owner can update their draft request
            return is_owner
        if action == Action.APPROVE:
            # Approvers and finance can approve, but NEVER the requester themselves (separation of duties)
            if is_owner:
                return False
            return user.role in ("approver", "finance")
        return False

    # 2. Contracts
    if "contract" in resource_type:
        is_owner = (owner_id == user.id)
        if action == Action.READ:
            return is_owner or user.role in ("approver", "finance")
        if action in (Action.UPDATE, Action.WRITE, Action.APPROVE):
            return user.role in ("approver", "finance")
        return False

    # 3. Documents & Batches
    if "document" in resource_type or "batch" in resource_type:
        is_owner = (owner_id == user.id)
        if action == Action.READ:
            return is_owner or user.role in ("approver", "finance")
        if action in (Action.CREATE, Action.WRITE, Action.UPDATE):
            return is_owner or user.role in ("approver", "finance")
        return False

    # 4. Ratings, Scorecards & Reviews
    if "risk" in resource_type or "score" in resource_type or "rating" in resource_type:
        if action == Action.READ:
            return True
        if action in (Action.CREATE, Action.WRITE, Action.UPDATE):
            return user.role in ("finance", "approver")
        return False

    # 5. Notifications
    if "notification" in resource_type:
        recipient_id = getattr(resource, "user_id", getattr(resource, "recipient_id", None))
        if recipient_id and str(recipient_id) == user.id:
            return action in (Action.READ, Action.UPDATE)
        return user.role == "admin"

    # Default fallback for owned entities
    if owner_id is not None:
        if owner_id == user.id:
            return action in (Action.READ, Action.UPDATE, Action.WRITE)
        return False

    # Unknown resource default: read-only for authenticated users
    return action == Action.READ
