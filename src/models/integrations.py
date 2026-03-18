"""
Pydantic models for integration endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# =============================================================================
# Response Models
# =============================================================================

class IntegrationResponse(BaseModel):
    """An available integration from the catalog."""
    id: str
    slug: str
    name: str
    vendor: str
    description: Optional[str] = None
    icon: Optional[str] = None
    is_active: bool


class ConnectionResponse(BaseModel):
    """A workspace's connection to an integration."""
    id: str
    integration: IntegrationResponse
    is_active: bool
    has_credentials: bool = Field(description="Whether credentials have been saved (never exposes actual values)")
    health_status: str = Field(description="healthy, unhealthy, or unknown")
    last_health_check_at: Optional[datetime] = None
    settings: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class HealthCheckResponse(BaseModel):
    """Result of a connection health check."""
    connection_id: str
    provider: str
    health_status: str
    message: str
    checked_at: datetime


# =============================================================================
# Request Models
# =============================================================================

class ConnexysCredentialsRequest(BaseModel):
    """Credentials for Connexys (Salesforce) integration."""
    instance_url: str = Field(description="Salesforce instance URL, e.g. https://company.my.salesforce.com")
    consumer_key: str = Field(description="Connected App Consumer Key")
    consumer_secret: str = Field(description="Connected App Consumer Secret")


class MicrosoftCredentialsRequest(BaseModel):
    """Credentials for Microsoft Graph API integration (Teams + Outlook)."""
    tenant_id: str = Field(description="Azure AD Tenant ID")
    client_id: str = Field(description="Azure App Registration Client ID")
    client_secret: str = Field(description="Azure App Registration Client Secret")


class UpdateConnectionSettingsRequest(BaseModel):
    """Update non-secret settings for a connection."""
    settings: dict = Field(default_factory=dict)
    is_active: Optional[bool] = None
