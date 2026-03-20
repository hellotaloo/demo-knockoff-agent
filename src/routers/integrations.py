"""
API endpoints for managing external integrations.
"""
import asyncio
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from src.auth.dependencies import AuthContext, require_workspace
from src.dependencies import get_pool
from src.services.integration_service import IntegrationService
from src.services.vacancy_import_service import VacancyImportService, get_sync_progress
from src.services.data_pushback_service import DataPushbackService
from src.models.integrations import (
    IntegrationResponse,
    ConnectionResponse,
    HealthCheckResponse,
    MappingSchemaResponse,
    ExportMappingSchemaResponse,
    SyncProgressResponse,
    SourceFieldInfo,
    PushbackResultResponse,
    ConnexysCredentialsRequest,
    MicrosoftCredentialsRequest,
    UpdateConnectionSettingsRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])


async def get_integration_service(pool=Depends(get_pool)) -> IntegrationService:
    return IntegrationService(pool)


# =============================================================================
# Catalog
# =============================================================================

@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """List all available integrations."""
    return await service.list_integrations()


# =============================================================================
# Connections
# =============================================================================

@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """List all connections for the current workspace."""
    return await service.list_connections(ctx.workspace_id)


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Get a single connection."""
    connection = await service.get_connection(connection_id, workspace_id=ctx.workspace_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.put("/connections/connexys", response_model=ConnectionResponse)
async def save_connexys_credentials(
    body: ConnexysCredentialsRequest,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Save or update Connexys (Salesforce) credentials."""
    return await service.save_credentials(
        workspace_id=ctx.workspace_id,
        provider_slug="connexys",
        credentials=body.model_dump(),
    )


@router.put("/connections/microsoft", response_model=ConnectionResponse)
async def save_microsoft_credentials(
    body: MicrosoftCredentialsRequest,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Save or update Microsoft credentials."""
    return await service.save_credentials(
        workspace_id=ctx.workspace_id,
        provider_slug="microsoft",
        credentials=body.model_dump(),
    )


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: UpdateConnectionSettingsRequest,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Update connection settings or active status."""
    return await service.update_connection(
        connection_id=connection_id,
        settings=body.settings,
        is_active=body.is_active,
        workspace_id=ctx.workspace_id,
    )


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Delete a connection and its credentials."""
    await service.delete_connection(connection_id, workspace_id=ctx.workspace_id)


# =============================================================================
# Field Mapping
# =============================================================================

@router.get("/connections/{connection_id}/mapping-schema", response_model=MappingSchemaResponse)
async def get_mapping_schema(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Get the field mapping schema for a connection (target fields, source fields, defaults)."""
    try:
        return await service.get_mapping_schema(connection_id, workspace_id=ctx.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/connections/{connection_id}/discover-fields", response_model=list[SourceFieldInfo])
async def discover_source_fields(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Discover available source fields from the external system via its describe API."""
    try:
        return await service.discover_source_fields(connection_id, workspace_id=ctx.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=f"Could not connect to external system: {str(e)}")
    except Exception as e:
        logger.error(f"Field discovery failed for connection {connection_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Field discovery failed: {str(e)}")


# =============================================================================
# Health Check
# =============================================================================

@router.post("/connections/{connection_id}/health-check", response_model=HealthCheckResponse)
async def check_connection_health(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Run a health check on a connection."""
    try:
        return await service.check_health(connection_id, workspace_id=ctx.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =============================================================================
# Vacancy Sync
# =============================================================================

@router.post("/sync", status_code=202)
async def start_sync(
    ctx: AuthContext = Depends(require_workspace),
    pool=Depends(get_pool),
):
    """
    Start a vacancy sync from the workspace's active ATS integration.

    Resolves the active connection automatically — no connection_id needed.
    Runs in the background; poll GET /integrations/sync/status for progress.
    """
    # Check if a sync is already running
    progress = get_sync_progress()
    if progress and progress.get("status") == "syncing":
        raise HTTPException(status_code=409, detail="Een sync is al bezig")

    service = VacancyImportService(pool)
    asyncio.create_task(service.sync(ctx.workspace_id))
    return {"status": "started", "message": "Sync gestart"}


@router.get("/sync/status", response_model=SyncProgressResponse)
async def get_sync_status(
    ctx: AuthContext = Depends(require_workspace),
):
    """Poll for the current sync progress."""
    progress = get_sync_progress()
    if not progress:
        return SyncProgressResponse(status="idle", message="Geen sync actief")
    return SyncProgressResponse(**progress)


# =============================================================================
# Data Push-back (Export to ATS)
# =============================================================================

@router.get("/connections/{connection_id}/export-mapping-schema", response_model=ExportMappingSchemaResponse)
async def get_export_mapping_schema(
    connection_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Get the export field mapping schema for data push-back configuration."""
    try:
        return await service.get_export_mapping_schema(connection_id, workspace_id=ctx.workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/connections/{connection_id}/discover-export-fields", response_model=list[SourceFieldInfo])
async def discover_export_target_fields(
    connection_id: UUID,
    sf_object: Optional[str] = None,
    ctx: AuthContext = Depends(require_workspace),
    service: IntegrationService = Depends(get_integration_service),
):
    """Discover available target fields on the Connexys export object."""
    try:
        return await service.discover_export_target_fields(
            connection_id, sf_object=sf_object, workspace_id=ctx.workspace_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError as e:
        raise HTTPException(status_code=502, detail=f"Could not connect to external system: {str(e)}")
    except Exception as e:
        logger.error(f"Export field discovery failed for connection {connection_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Field discovery failed: {str(e)}")


@router.post("/applications/{application_id}/push-to-ats", response_model=PushbackResultResponse)
async def push_application_to_ats(
    application_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    pool=Depends(get_pool),
):
    """Push a single application's screening results back to Connexys."""
    service = DataPushbackService(pool)
    return await service.push_application(application_id, ctx.workspace_id)


@router.post("/vacancies/{vacancy_id}/push-to-ats", response_model=list[PushbackResultResponse])
async def push_vacancy_applications_to_ats(
    vacancy_id: UUID,
    ctx: AuthContext = Depends(require_workspace),
    pool=Depends(get_pool),
):
    """Push all unsynced completed applications for a vacancy to Connexys."""
    service = DataPushbackService(pool)
    return await service.push_batch(vacancy_id, ctx.workspace_id)
