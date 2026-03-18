"""
API endpoints for managing external integrations.
"""
import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from src.dependencies import get_pool
from src.services.integration_service import IntegrationService
from src.models.integrations import (
    IntegrationResponse,
    ConnectionResponse,
    HealthCheckResponse,
    ConnexysCredentialsRequest,
    MicrosoftCredentialsRequest,
    UpdateConnectionSettingsRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["Integrations"])

DEFAULT_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


async def get_integration_service(pool=Depends(get_pool)) -> IntegrationService:
    return IntegrationService(pool)


# =============================================================================
# Catalog
# =============================================================================

@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(service: IntegrationService = Depends(get_integration_service)):
    """List all available integrations."""
    return await service.list_integrations()


# =============================================================================
# Connections
# =============================================================================

@router.get("/connections", response_model=list[ConnectionResponse])
async def list_connections(service: IntegrationService = Depends(get_integration_service)):
    """List all connections for the current workspace."""
    return await service.list_connections(DEFAULT_WORKSPACE_ID)


@router.get("/connections/{connection_id}", response_model=ConnectionResponse)
async def get_connection(
    connection_id: UUID,
    service: IntegrationService = Depends(get_integration_service),
):
    """Get a single connection."""
    connection = await service.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


@router.put("/connections/connexys", response_model=ConnectionResponse)
async def save_connexys_credentials(
    body: ConnexysCredentialsRequest,
    service: IntegrationService = Depends(get_integration_service),
):
    """Save or update Connexys (Salesforce) credentials."""
    return await service.save_credentials(
        workspace_id=DEFAULT_WORKSPACE_ID,
        provider_slug="connexys",
        credentials=body.model_dump(),
    )


@router.put("/connections/microsoft", response_model=ConnectionResponse)
async def save_microsoft_credentials(
    body: MicrosoftCredentialsRequest,
    service: IntegrationService = Depends(get_integration_service),
):
    """Save or update Microsoft credentials."""
    return await service.save_credentials(
        workspace_id=DEFAULT_WORKSPACE_ID,
        provider_slug="microsoft",
        credentials=body.model_dump(),
    )


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse)
async def update_connection(
    connection_id: UUID,
    body: UpdateConnectionSettingsRequest,
    service: IntegrationService = Depends(get_integration_service),
):
    """Update connection settings or active status."""
    return await service.update_connection(
        connection_id=connection_id,
        settings=body.settings,
        is_active=body.is_active,
    )


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID,
    service: IntegrationService = Depends(get_integration_service),
):
    """Delete a connection and its credentials."""
    await service.delete_connection(connection_id)


# =============================================================================
# Health Check
# =============================================================================

@router.post("/connections/{connection_id}/health-check", response_model=HealthCheckResponse)
async def check_connection_health(
    connection_id: UUID,
    service: IntegrationService = Depends(get_integration_service),
):
    """Run a health check on a connection."""
    try:
        return await service.check_health(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
