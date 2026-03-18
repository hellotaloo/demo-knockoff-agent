"""
Service for managing external integrations.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import asyncpg

from src.repositories.integration_repo import IntegrationRepository
from src.models.integrations import (
    IntegrationResponse,
    ConnectionResponse,
    HealthCheckResponse,
)

logger = logging.getLogger(__name__)


class IntegrationService:
    def __init__(self, pool: asyncpg.Pool):
        self.repo = IntegrationRepository(pool)

    # =========================================================================
    # Catalog
    # =========================================================================

    async def list_integrations(self) -> list[IntegrationResponse]:
        rows = await self.repo.list_integrations()
        return [
            IntegrationResponse(
                id=str(row["id"]),
                slug=row["slug"],
                name=row["name"],
                vendor=row["vendor"],
                description=row["description"],
                icon=row["icon"],
                is_active=row["is_active"],
            )
            for row in rows
        ]

    # =========================================================================
    # Connections
    # =========================================================================

    async def list_connections(self, workspace_id: UUID) -> list[ConnectionResponse]:
        rows = await self.repo.list_connections(workspace_id)
        return [self._build_connection_response(row) for row in rows]

    async def get_connection(self, connection_id: UUID) -> Optional[ConnectionResponse]:
        row = await self.repo.get_connection(connection_id)
        if not row:
            return None
        return self._build_connection_response(row)

    async def save_credentials(
        self, workspace_id: UUID, provider_slug: str, credentials: dict
    ) -> ConnectionResponse:
        """Save credentials for a provider. Creates or updates the connection."""
        integration = await self.repo.get_integration_by_slug(provider_slug)
        if not integration:
            raise ValueError(f"Unknown integration provider: {provider_slug}")

        credentials_json = json.dumps(credentials)

        result = await self.repo.upsert_connection(
            workspace_id=workspace_id,
            integration_id=integration["id"],
            credentials=credentials_json,
            settings="{}",
            is_active=True,
        )

        connection = await self.repo.get_connection(result["id"])
        return self._build_connection_response(connection)

    async def update_connection(
        self, connection_id: UUID, settings: Optional[dict] = None, is_active: Optional[bool] = None
    ) -> ConnectionResponse:
        """Update settings and/or active status."""
        settings_json = json.dumps(settings) if settings else None

        if settings_json:
            await self.repo.update_settings(connection_id, settings_json, is_active)
        elif is_active is not None:
            await self.repo.update_settings(connection_id, "{}", is_active)

        connection = await self.repo.get_connection(connection_id)
        return self._build_connection_response(connection)

    async def delete_connection(self, connection_id: UUID) -> None:
        await self.repo.delete_connection(connection_id)

    # =========================================================================
    # Health Checks
    # =========================================================================

    async def check_health(self, connection_id: UUID) -> HealthCheckResponse:
        """Run a health check for a connection."""
        row = await self.repo.get_connection(connection_id)
        if not row:
            raise ValueError("Connection not found")

        provider = row["slug"]
        credentials = json.loads(row["credentials"]) if isinstance(row["credentials"], str) else row["credentials"]

        status = "unhealthy"
        message = "Unknown provider"

        try:
            if provider == "connexys":
                status, message = await self._check_connexys(credentials)
            elif provider == "microsoft":
                status, message = await self._check_microsoft(credentials)
            else:
                message = f"Health check not implemented for {provider}"
        except Exception as e:
            status = "unhealthy"
            message = str(e)
            logger.error(f"Health check failed for {provider}: {e}")

        await self.repo.update_health_status(connection_id, status)

        return HealthCheckResponse(
            connection_id=str(connection_id),
            provider=provider,
            health_status=status,
            message=message,
            checked_at=datetime.now(timezone.utc),
        )

    async def _check_connexys(self, credentials: dict) -> tuple[str, str]:
        """Check Salesforce/Connexys connectivity via OAuth client_credentials flow."""
        import httpx

        instance_url = credentials["instance_url"].rstrip("/")
        # Normalize lightning.force.com URLs to my.salesforce.com
        instance_url = instance_url.replace(".lightning.force.com", ".my.salesforce.com")
        token_url = f"{instance_url}/services/oauth2/token"

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": credentials["consumer_key"],
                "client_secret": credentials["consumer_secret"],
            })

            if resp.status_code != 200:
                error = resp.json().get("error_description", "Authentication failed")
                return "unhealthy", error

            token_data = resp.json()
            access_token = token_data["access_token"]
            sf_instance = token_data.get("instance_url", instance_url)

            # Verify API access with a simple query
            api_resp = await client.get(
                f"{sf_instance}/services/data/v62.0/limits",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if api_resp.status_code == 200:
                return "healthy", f"Connected to Salesforce ({sf_instance})"
            else:
                return "unhealthy", f"Auth OK but API call failed ({api_resp.status_code})"

    async def _check_microsoft(self, credentials: dict) -> tuple[str, str]:
        """Check Microsoft Graph API connectivity."""
        import httpx

        token_url = f"https://login.microsoftonline.com/{credentials['tenant_id']}/oauth2/v2.0/token"

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data={
                "grant_type": "client_credentials",
                "client_id": credentials["client_id"],
                "client_secret": credentials["client_secret"],
                "scope": "https://graph.microsoft.com/.default",
            })

            if resp.status_code == 200:
                return "healthy", "Connected to Microsoft Graph API"
            else:
                error = resp.json().get("error_description", "Authentication failed")
                return "unhealthy", error

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _build_connection_response(row: asyncpg.Record) -> ConnectionResponse:
        credentials = row["credentials"]
        if isinstance(credentials, str):
            credentials = json.loads(credentials)

        has_credentials = bool(credentials and credentials != {})

        return ConnectionResponse(
            id=str(row["id"]),
            integration=IntegrationResponse(
                id=str(row["integration_id"]),
                slug=row["slug"],
                name=row["name"],
                vendor=row["vendor"],
                description=row["description"],
                icon=row["icon"],
                is_active=row["integration_is_active"],
            ),
            is_active=row["is_active"],
            has_credentials=has_credentials,
            health_status=row["health_status"],
            last_health_check_at=row["last_health_check_at"],
            settings=json.loads(row["settings"]) if isinstance(row["settings"], str) else row["settings"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
