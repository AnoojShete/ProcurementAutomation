import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_connection():
    db_url = os.environ.get(
        "DATABASE_URL", 
        "postgresql://postgres:postgres@localhost:5432/postgres"
    )
    # Handle asyncpg URL format if used by other services
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(db_url)

def is_live_mode_enabled() -> bool:
    """Checks if live verification mode is enabled globally."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT live_verification_enabled FROM system_settings WHERE id = 1")
                row = cur.fetchone()
                if row:
                    return bool(row[0])
        return False
    except Exception as e:
        print(f"Error checking live mode: {e}")
        return False

def check_and_reserve_quota(api_name: str) -> bool:
    """
    Atomically checks remaining quota and increments it.
    Returns False if live mode is off OR if quota is at/past safety cutoff.
    """
    if not is_live_mode_enabled():
        return False
        
    cutoff_ratio = 0.8
    if api_name == "gstin_live":
        # Specific hardcoded cutoff for GSTIN due to very low limit
        hard_cutoff = 15
    else:
        hard_cutoff = None

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Atomically update and return the state
                cur.execute(
                    """
                    UPDATE api_quota_usage 
                    SET calls_used = calls_used + 1 
                    WHERE api_name = %s 
                      AND (
                          (calls_used + 1) <= calls_limit * %s
                          AND (%s::int IS NULL OR (calls_used + 1) <= %s)
                      )
                    RETURNING calls_used, calls_limit
                    """,
                    (api_name, cutoff_ratio, hard_cutoff, hard_cutoff)
                )
                row = cur.fetchone()
                
                # If row is returned, the update succeeded (quota reserved)
                if row:
                    return True
                
                return False
    except Exception as e:
        print(f"Error reserving quota for {api_name}: {e}")
        return False
