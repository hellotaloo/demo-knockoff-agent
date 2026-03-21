"""
Admin router - super admin endpoints for platform-wide management.
"""
import logging
from typing import List

from fastapi import APIRouter, Depends
import asyncpg

from src.database import get_db_pool
from src.services import WorkspaceService
from src.auth.dependencies import require_super_admin, UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# =============================================================================
# Dependencies
# =============================================================================

async def get_workspace_service(pool: asyncpg.Pool = Depends(get_db_pool)) -> WorkspaceService:
    """Get WorkspaceService instance."""
    return WorkspaceService(pool)


# =============================================================================
# Workspace Management
# =============================================================================

@router.get("/workspaces")
async def list_all_workspaces(
    user: UserProfile = Depends(require_super_admin),
    service: WorkspaceService = Depends(get_workspace_service),
):
    """
    List all workspaces on the platform.

    Super admin only (@taloo.eu accounts).
    """
    return await service.list_all_workspaces()
