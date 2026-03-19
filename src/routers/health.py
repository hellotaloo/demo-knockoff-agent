"""
Health check router with database connectivity verification and system status.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.dependencies import get_pool
from src.auth.dependencies import AuthContext, require_workspace
from src.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    LIVEKIT_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Health"])

# Timeout for individual service pings (seconds)
PING_TIMEOUT = 5


# =============================================================================
# Response Models
# =============================================================================

class ServiceStatusItem(BaseModel):
    name: str
    slug: str
    status: str  # "online" | "offline" | "degraded" | "not_configured"
    description: str


class IntegrationStatusItem(BaseModel):
    name: str
    slug: str
    status: str  # "online" | "offline" | "unknown"
    description: str
    last_checked_at: Optional[str] = None


class SystemStatusResponse(BaseModel):
    overall: str  # "online" | "degraded" | "offline"
    services: list[ServiceStatusItem]
    integrations: list[IntegrationStatusItem]


# =============================================================================
# Service Pings
# =============================================================================

async def _ping_gemini() -> tuple[str, str]:
    """Ping Gemini API by listing models (lightweight, no inference)."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return "not_configured", "Taalmodel niet ingesteld"
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        models = await client.aio.models.list()
        if models:
            return "online", "Taalmodel bereikbaar"
        return "offline", "Taalmodel niet beschikbaar"
    except Exception as e:
        logger.warning(f"Gemini ping failed: {e}")
        return "offline", "Taalmodel niet bereikbaar"


async def _ping_livekit() -> tuple[str, str]:
    """Ping LiveKit Cloud by listing rooms (read-only, no dispatch)."""
    if not LIVEKIT_URL or not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        return "not_configured", "Voice pipeline niet ingesteld"
    try:
        from livekit import api as lk_api
        from livekit.protocol import room as proto_room
        lkapi = lk_api.LiveKitAPI(
            url=LIVEKIT_URL,
            api_key=LIVEKIT_API_KEY,
            api_secret=LIVEKIT_API_SECRET,
        )
        await lkapi.room.list_rooms(proto_room.ListRoomsRequest())
        await lkapi.aclose()
        return "online", "Voice pipeline bereikbaar"
    except Exception as e:
        logger.warning(f"LiveKit ping failed: {e}")
        return "offline", "Voice pipeline niet bereikbaar"


async def _ping_twilio() -> tuple[str, str]:
    """Ping Twilio by fetching account info (no messages sent)."""
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        return "not_configured", "Berichten niet ingesteld"
    try:
        from twilio.rest import Client
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        # Twilio SDK is synchronous — run in executor
        loop = asyncio.get_event_loop()
        account = await loop.run_in_executor(
            None,
            lambda: client.api.accounts(TWILIO_ACCOUNT_SID).fetch()
        )
        if account and account.status == "active":
            return "online", "Berichten bereikbaar"
        return "degraded", "Berichtenservice beperkt"
    except Exception as e:
        logger.warning(f"Twilio ping failed: {e}")
        return "offline", "Berichten niet bereikbaar"


async def _ping_with_timeout(coro, timeout: int = PING_TIMEOUT) -> tuple[str, str]:
    """Wrap a ping coroutine with a timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        return "offline", "Timeout bij verbindingscheck"


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/health")
async def health_check(pool: asyncpg.Pool = Depends(get_pool)):
    """Health check endpoint with database connectivity verification.

    Returns 200 if the service and database are healthy.
    Returns 503 if the database is unreachable.
    """
    try:
        await pool.fetchval("SELECT 1")
        return {"status": "healthy", "service": "taloo-backend", "database": "connected"}
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "service": "taloo-backend", "database": str(e)}
        )


@router.get("/health/pool")
async def pool_status(pool: asyncpg.Pool = Depends(get_pool)):
    """Connection pool status endpoint for monitoring.

    Returns pool statistics useful for debugging connection issues:
    - size: Current number of connections in the pool
    - free_size: Number of idle connections available
    - min_size: Minimum pool size configured
    - max_size: Maximum pool size configured
    """
    return {
        "size": pool.get_size(),
        "free_size": pool.get_idle_size(),
        "min_size": pool.get_min_size(),
        "max_size": pool.get_max_size(),
    }


@router.get("/health/status", response_model=SystemStatusResponse)
async def system_status(pool: asyncpg.Pool = Depends(get_pool), ctx: AuthContext = Depends(require_workspace)):
    """Aggregated system status for the status dropdown.

    Returns status of:
    - Core services: Platform (API+DB), LLM (Gemini), Voice (LiveKit), WhatsApp (Twilio)
    - External integrations: Connexys, Microsoft, etc.

    Each service is pinged concurrently with a 5s timeout.
    Integration status is based on the last stored health check result.
    """
    services: list[ServiceStatusItem] = []
    integrations: list[IntegrationStatusItem] = []

    # --- Run all service pings concurrently ---
    db_ok = False
    try:
        await pool.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass

    llm_result, voice_result, whatsapp_result = await asyncio.gather(
        _ping_with_timeout(_ping_gemini()),
        _ping_with_timeout(_ping_livekit()),
        _ping_with_timeout(_ping_twilio()),
    )

    # --- Platform (API + Database) ---
    services.append(ServiceStatusItem(
        name="Platform",
        slug="platform",
        status="online" if db_ok else "offline",
        description="API & database operationeel" if db_ok else "Database niet bereikbaar",
    ))

    # --- LLM (Gemini) ---
    services.append(ServiceStatusItem(
        name="LLM",
        slug="llm",
        status=llm_result[0],
        description=llm_result[1],
    ))

    # --- Voice (LiveKit) ---
    services.append(ServiceStatusItem(
        name="Voice",
        slug="voice",
        status=voice_result[0],
        description=voice_result[1],
    ))

    # --- WhatsApp (Twilio) ---
    services.append(ServiceStatusItem(
        name="WhatsApp",
        slug="whatsapp",
        status=whatsapp_result[0],
        description=whatsapp_result[1],
    ))

    # --- External Integrations (from DB) ---
    try:
        rows = await pool.fetch("""
            SELECT
                ic.is_active, ic.health_status, ic.last_health_check_at,
                ic.credentials,
                i.slug, i.name
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1
            ORDER BY i.name
        """, ctx.workspace_id)

        for row in rows:
            credentials = row["credentials"]
            if isinstance(credentials, str):
                credentials = json.loads(credentials)
            has_credentials = bool(credentials and credentials != {})

            if not has_credentials:
                int_status = "not_configured"
                int_description = "Geen credentials ingesteld"
            elif not row["is_active"]:
                int_status = "offline"
                int_description = "Uitgeschakeld"
            elif row["health_status"] == "healthy":
                int_status = "online"
                int_description = "Verbonden"
            elif row["health_status"] == "unhealthy":
                int_status = "offline"
                int_description = "Verbinding mislukt"
            else:
                int_status = "unknown"
                int_description = "Status onbekend"

            last_checked = None
            if row["last_health_check_at"]:
                last_checked = row["last_health_check_at"].isoformat()

            integrations.append(IntegrationStatusItem(
                name=row["name"],
                slug=row["slug"],
                status=int_status,
                description=int_description,
                last_checked_at=last_checked,
            ))
    except Exception as e:
        logger.error(f"Failed to fetch integration statuses: {e}")

    # --- Overall status ---
    all_statuses = [s.status for s in services] + [i.status for i in integrations]
    if any(s == "offline" for s in all_statuses):
        overall = "degraded"
    elif any(s in ("degraded", "unknown") for s in all_statuses):
        overall = "degraded"
    else:
        overall = "online"

    return SystemStatusResponse(
        overall=overall,
        services=services,
        integrations=integrations,
    )
