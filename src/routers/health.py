"""
Health check router with database connectivity verification.
"""
import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.dependencies import get_pool

router = APIRouter(tags=["Health"])


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
