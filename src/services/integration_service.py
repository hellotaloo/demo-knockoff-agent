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
    MappingFieldInfo,
    SourceFieldInfo,
    MappingSchemaResponse,
    ExportFieldInfo,
    ExportMappingSchemaResponse,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Mapping Configuration — Connexys (Salesforce)
# =============================================================================

# Default Salesforce object for Connexys vacancy data
CONNEXYS_DEFAULT_SF_OBJECT = "cxsrec__cxsPosition__c"

TALOO_TARGET_FIELDS = [
    MappingFieldInfo(name="title", label="Vacaturenaam", type="text", required=True, description="Titel van de vacature"),
    MappingFieldInfo(name="company", label="Bedrijfsnaam", type="text", required=True, description="Naam van het klantbedrijf"),
    MappingFieldInfo(name="location", label="Locatie", type="text", required=False, description="Werklocatie (postcode + stad)"),
    MappingFieldInfo(name="description", label="Omschrijving", type="html", required=False, description="Volledige vacaturetekst (functieomschrijving, eisen, voorwaarden)"),
    MappingFieldInfo(name="source_id", label="Extern ID", type="text", required=True, description="Uniek ID uit het bronsysteem"),
    MappingFieldInfo(name="start_date", label="Startdatum", type="date", required=False, description="Startdatum van de inzet"),
    MappingFieldInfo(name="recruiter_email", label="Recruiter e-mail", type="text", required=False, description="E-mailadres van de recruiter/eigenaar"),
    MappingFieldInfo(name="recruiter_name", label="Recruiter naam", type="text", required=False, description="Volledige naam van de recruiter"),
    MappingFieldInfo(name="recruiter_phone", label="Recruiter telefoon", type="text", required=False, description="Telefoonnummer van de recruiter"),
    MappingFieldInfo(name="recruiter_role", label="Recruiter functie", type="text", required=False, description="Functietitel van de recruiter"),
    MappingFieldInfo(name="office_name", label="Kantoornaam", type="text", required=False, description="Naam van het kantoor"),
    MappingFieldInfo(name="office_email", label="Kantoor e-mail", type="text", required=False, description="E-mailadres van het kantoor"),
    MappingFieldInfo(name="office_phone", label="Kantoor telefoon", type="text", required=False, description="Telefoonnummer van het kantoor"),
    MappingFieldInfo(name="office_address", label="Kantoor adres", type="text", required=False, description="Volledig adres van het kantoor"),
    MappingFieldInfo(name="sync_filter", label="Sync filter", type="boolean", required=False, description="Veld dat bepaalt of de vacature gesynchroniseerd wordt"),
    MappingFieldInfo(name="is_online", label="Online pre-screening", type="boolean", required=False, description="true = online pre-screening, false = offline"),
]

CONNEXYS_SOURCE_FIELDS = [
    # Vacancy fields
    SourceFieldInfo(name="Id", label="Record ID", category="vacancy"),
    SourceFieldInfo(name="Name", label="Vacaturenaam", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Status__c", label="Status", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Account__c", label="Klant ID", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Account_name__c", label="Klantnaam", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Job_description__c", label="Functieomschrijving", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Job_requirements__c", label="Functie-eisen", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Compensation_benefits__c", label="Arbeidsvoorwaarden", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Country__c", label="Land", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Contract_type__c", label="Soort contract", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Job_start_date__c", label="Startdatum inzet", category="vacancy"),
    SourceFieldInfo(name="cxsrec__Number_of_employees_to_be_hired__c", label="Aantal te werven", category="vacancy"),
    SourceFieldInfo(name="job_vdab_worklocation__c", label="Locatie (postcode + stad)", category="vacancy"),
    SourceFieldInfo(name="job_sector__c", label="Sector", category="vacancy"),
    SourceFieldInfo(name="job_section__c", label="Statuut", category="vacancy"),
    SourceFieldInfo(name="job_language__c", label="Taal", category="vacancy"),
    SourceFieldInfo(name="job_work_regime__c", label="Werkregime", category="vacancy"),
    SourceFieldInfo(name="job_brand__c", label="Brand", category="vacancy"),
    SourceFieldInfo(name="cbx_itzu_website__c", label="ITZU Website (online/offline)", category="vacancy"),
    SourceFieldInfo(name="sync_to_taloo__c", label="Sync naar Taloo", category="vacancy"),
    SourceFieldInfo(name="CreatedDate", label="Aanmaakdatum", category="vacancy"),
    SourceFieldInfo(name="LastModifiedDate", label="Laatste wijziging", category="vacancy"),
    # Owner (recruiter) fields
    SourceFieldInfo(name="Owner.Email", label="Eigenaar e-mail", category="owner"),
    SourceFieldInfo(name="Owner.Name", label="Eigenaar naam", category="owner"),
    SourceFieldInfo(name="Owner.Phone", label="Eigenaar telefoon", category="owner"),
    SourceFieldInfo(name="Owner.Title", label="Eigenaar functie", category="owner"),
    # Office fields
    SourceFieldInfo(name="job_office__r.Name", label="Kantoornaam", category="office"),
    SourceFieldInfo(name="job_office__r.office_email__c", label="Kantoor e-mail", category="office"),
    SourceFieldInfo(name="job_office__r.office_phone__c", label="Kantoor telefoon", category="office"),
    SourceFieldInfo(name="job_office__r.Id", label="Kantoor ID", category="office"),
    SourceFieldInfo(name="job_office__r.office_street__c", label="Kantoor straat", category="office"),
    SourceFieldInfo(name="job_office__r.office_number__c", label="Kantoor nummer", category="office"),
    SourceFieldInfo(name="job_office__r.office_postalcode__c", label="Kantoor postcode", category="office"),
    SourceFieldInfo(name="job_office__r.office_city__c", label="Kantoor plaats", category="office"),
]

CONNEXYS_DEFAULT_MAPPING = {
    "title": {"template": "{{Name}}"},
    "company": {"template": "{{cxsrec__Account_name__c}}"},
    "location": {"template": "{{job_vdab_worklocation__c}}"},
    "description": {"template": "{{cxsrec__Job_description__c}}\n{{cxsrec__Job_requirements__c}}\n{{cxsrec__Compensation_benefits__c}}"},
    "source_id": {"template": "{{Id}}"},
    "start_date": {"template": "{{cxsrec__Job_start_date__c}}"},
    "recruiter_email": {"template": "{{Owner.Email}}"},
    "recruiter_name": {"template": "{{Owner.Name}}"},
    "recruiter_phone": {"template": "{{Owner.Phone}}"},
    "recruiter_role": {"template": "{{Owner.Title}}"},
    "office_name": {"template": "{{job_office__r.Name}}"},
    "office_email": {"template": "{{job_office__r.office_email__c}}"},
    "office_phone": {"template": "{{job_office__r.office_phone__c}}"},
    "office_address": {"template": "{{job_office__r.office_street__c}} {{job_office__r.office_number__c}}, {{job_office__r.office_postalcode__c}} {{job_office__r.office_city__c}}"},
    "office_source_id": {"template": "{{job_office__r.Id}}"},
    "sync_filter": {"template": "{{sync_to_taloo__c}}"},
    "is_online": {"template": "{{cbx_itzu_website__c}}"},
}

PROVIDER_MAPPING_CONFIG = {
    "connexys": {
        "target_fields": TALOO_TARGET_FIELDS,
        "source_fields": CONNEXYS_SOURCE_FIELDS,
        "default_mapping": CONNEXYS_DEFAULT_MAPPING,
    },
}


# =============================================================================
# Export (Data Push-back) Configuration
# =============================================================================

# Default Salesforce object for pushing screening results
CONNEXYS_DEFAULT_EXPORT_SF_OBJECT = "cxsrec__cxsCandidate__c"

# Taloo application fields available for export
TALOO_EXPORT_SOURCE_FIELDS = [
    ExportFieldInfo(name="candidate_name", label="Kandidaatnaam", type="text", description="Volledige naam van de kandidaat"),
    ExportFieldInfo(name="candidate_phone", label="Telefoonnummer", type="text", description="Telefoonnummer van de kandidaat"),
    ExportFieldInfo(name="candidate_email", label="E-mailadres", type="text", description="E-mailadres van de kandidaat"),
    ExportFieldInfo(name="summary", label="Samenvatting", type="html", description="AI-gegenereerde executive samenvatting van het screening-gesprek"),
    ExportFieldInfo(name="open_questions_score", label="Kwalificatiescore", type="number", description="Gemiddelde score op open vragen (0-100)"),
    ExportFieldInfo(name="qualified", label="Gekwalificeerd", type="boolean", description="Of de kandidaat is geslaagd voor de screening"),
    ExportFieldInfo(name="knockout_passed", label="Knockout geslaagd", type="number", description="Aantal geslaagde knockoutvragen"),
    ExportFieldInfo(name="knockout_total", label="Knockout totaal", type="number", description="Totaal aantal knockoutvragen"),
    ExportFieldInfo(name="knockout_result", label="Knockout resultaat", type="text", description="Knockout geslaagd/totaal als tekst (bijv. '3/4')"),
    ExportFieldInfo(name="answers_formatted", label="Vragen & antwoorden", type="html", description="Alle vragen en antwoorden geformateerd als tekst"),
    ExportFieldInfo(name="channel", label="Kanaal", type="text", description="Screeningkanaal (whatsapp/voice/cv)"),
    ExportFieldInfo(name="interaction_seconds", label="Duur (seconden)", type="number", description="Duur van de interactie in seconden"),
    ExportFieldInfo(name="interview_slot", label="Interviewmoment", type="text", description="Geselecteerd interviewmoment"),
    ExportFieldInfo(name="completed_at", label="Afgerond op", type="datetime", description="Datum/tijd waarop screening is afgerond"),
    ExportFieldInfo(name="vacancy_source_id", label="Vacature extern ID", type="text", description="Het externe ID van de vacature (voor koppeling in het ATS)"),
]

PROVIDER_EXPORT_CONFIG = {
    "connexys": {
        "source_fields": TALOO_EXPORT_SOURCE_FIELDS,
        "default_sf_object": CONNEXYS_DEFAULT_EXPORT_SF_OBJECT,
        "default_mapping": {},  # Empty until client provides Connexys field names
    },
}


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

    async def _verify_connection_ownership(self, connection_id: UUID, workspace_id: UUID) -> asyncpg.Record:
        """Fetch a connection and verify it belongs to the given workspace."""
        row = await self.repo.get_connection(connection_id)
        if not row or row["workspace_id"] != workspace_id:
            raise ValueError("Connection not found")
        return row

    async def get_connection(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> Optional[ConnectionResponse]:
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
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
        self, connection_id: UUID, settings: Optional[dict] = None, is_active: Optional[bool] = None,
        workspace_id: Optional[UUID] = None,
    ) -> ConnectionResponse:
        """Update settings and/or active status. Merges incoming settings with existing ones."""
        if workspace_id:
            await self._verify_connection_ownership(connection_id, workspace_id)

        if settings:
            # Merge with existing settings to avoid wiping field_cache, field_mapping, etc.
            row = await self.repo.get_connection(connection_id)
            if not row:
                raise ValueError("Connection not found")
            existing = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
            existing.update(settings)
            await self.repo.update_settings(connection_id, json.dumps(existing), is_active)
        elif is_active is not None:
            await self.repo.update_settings(connection_id, None, is_active)

        connection = await self.repo.get_connection(connection_id)
        return self._build_connection_response(connection)

    async def delete_connection(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> None:
        if workspace_id:
            await self._verify_connection_ownership(connection_id, workspace_id)
        await self.repo.delete_connection(connection_id)

    # =========================================================================
    # Field Mapping
    # =========================================================================

    async def get_mapping_schema(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> MappingSchemaResponse:
        """Return the mapping schema for the frontend editor."""
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
            row = await self.repo.get_connection(connection_id)
        if not row:
            raise ValueError("Connection not found")

        provider = row["slug"]
        config = PROVIDER_MAPPING_CONFIG.get(provider)
        if not config:
            raise ValueError(f"No mapping configuration for provider: {provider}")

        settings = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
        current = settings.get("field_mapping", {}).get("mappings")

        # Use cached source fields if available, otherwise fall back to hardcoded defaults
        source_fields = config["source_fields"]
        field_cache = settings.get("field_cache")
        if field_cache and field_cache.get("source_fields"):
            source_fields = [SourceFieldInfo(**f) for f in field_cache["source_fields"]]

        return MappingSchemaResponse(
            target_fields=config["target_fields"],
            source_fields=source_fields,
            default_mapping=config["default_mapping"],
            current_mapping=current,
        )

    async def discover_source_fields(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> list[SourceFieldInfo]:
        """Discover available source fields from the external system and cache them."""
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
            row = await self.repo.get_connection(connection_id)
        if not row:
            raise ValueError("Connection not found")

        provider = row["slug"]
        credentials = json.loads(row["credentials"]) if isinstance(row["credentials"], str) else row["credentials"]
        settings = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})

        if provider == "connexys":
            sf_object = settings.get("sf_object", CONNEXYS_DEFAULT_SF_OBJECT)
            fields = await self._discover_connexys_fields(credentials, sf_object)
        else:
            raise ValueError(f"Field discovery not supported for provider: {provider}")

        # Save to settings.field_cache
        settings = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
        settings["field_cache"] = {
            "source_fields": [f.model_dump() for f in fields],
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.repo.update_settings(connection_id, json.dumps(settings))

        return fields

    # =========================================================================
    # Export Mapping (Data Push-back)
    # =========================================================================

    async def get_export_mapping_schema(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> ExportMappingSchemaResponse:
        """Return the export mapping schema for the data push-back editor."""
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
            row = await self.repo.get_connection(connection_id)
        if not row:
            raise ValueError("Connection not found")

        provider = row["slug"]
        config = PROVIDER_EXPORT_CONFIG.get(provider)
        if not config:
            raise ValueError(f"No export configuration for provider: {provider}")

        settings = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})
        pushback = settings.get("data_pushback", {})
        current = pushback.get("mappings")

        # Use cached export target fields if available
        target_fields = []
        export_cache = settings.get("export_field_cache")
        if export_cache and export_cache.get("target_fields"):
            target_fields = [SourceFieldInfo(**f) for f in export_cache["target_fields"]]

        return ExportMappingSchemaResponse(
            source_fields=config["source_fields"],
            target_fields=target_fields,
            default_mapping=config["default_mapping"],
            current_mapping=current,
        )

    async def discover_export_target_fields(
        self, connection_id: UUID, sf_object: Optional[str] = None, workspace_id: Optional[UUID] = None
    ) -> list[SourceFieldInfo]:
        """Discover available target fields on the Connexys export object and cache them."""
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
            row = await self.repo.get_connection(connection_id)
        if not row:
            raise ValueError("Connection not found")

        provider = row["slug"]
        credentials = json.loads(row["credentials"]) if isinstance(row["credentials"], str) else row["credentials"]
        settings = json.loads(row["settings"]) if isinstance(row["settings"], str) else (row["settings"] or {})

        if provider == "connexys":
            config = PROVIDER_EXPORT_CONFIG.get(provider, {})
            target_object = sf_object or settings.get("data_pushback", {}).get("sf_object") or config.get("default_sf_object", CONNEXYS_DEFAULT_EXPORT_SF_OBJECT)
            fields = await self._discover_connexys_fields(credentials, target_object)
        else:
            raise ValueError(f"Export field discovery not supported for provider: {provider}")

        # Cache in settings.export_field_cache
        settings["export_field_cache"] = {
            "target_fields": [f.model_dump() for f in fields],
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }
        # Also store the sf_object in data_pushback settings
        pushback = settings.setdefault("data_pushback", {})
        pushback["sf_object"] = target_object
        await self.repo.update_settings(connection_id, json.dumps(settings))

        return fields

    # =========================================================================
    # Health Checks
    # =========================================================================

    async def check_health(self, connection_id: UUID, workspace_id: Optional[UUID] = None) -> HealthCheckResponse:
        """Run a health check for a connection."""
        if workspace_id:
            row = await self._verify_connection_ownership(connection_id, workspace_id)
        else:
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

    @staticmethod
    async def _get_connexys_token(credentials: dict) -> tuple[str, str]:
        """Authenticate to Salesforce and return (access_token, instance_url)."""
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
                raise ConnectionError(error)

            token_data = resp.json()
            return token_data["access_token"], token_data.get("instance_url", instance_url)

    async def _check_connexys(self, credentials: dict) -> tuple[str, str]:
        """Check Salesforce/Connexys connectivity via OAuth client_credentials flow."""
        import httpx

        try:
            access_token, sf_instance = await self._get_connexys_token(credentials)
        except ConnectionError as e:
            return "unhealthy", str(e)

        async with httpx.AsyncClient() as client:
            api_resp = await client.get(
                f"{sf_instance}/services/data/v62.0/limits",
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if api_resp.status_code == 200:
                return "healthy", f"Connected to Salesforce ({sf_instance})"
            else:
                return "unhealthy", f"Auth OK but API call failed ({api_resp.status_code})"

    async def _discover_connexys_fields(self, credentials: dict, sf_object: str) -> list[SourceFieldInfo]:
        """Discover available fields from Salesforce by calling the describe API."""
        import httpx

        access_token, sf_instance = await self._get_connexys_token(credentials)
        sf_api = f"{sf_instance}/services/data/v62.0"
        headers = {"Authorization": f"Bearer {access_token}"}

        # Salesforce field types we consider useful for mapping
        USEFUL_TYPES = {
            "string", "textarea", "email", "phone", "url", "picklist",
            "multipicklist", "boolean", "date", "datetime", "double",
            "currency", "int", "percent", "id", "reference",
        }
        # System fields to exclude
        SYSTEM_FIELDS = {
            "IsDeleted", "SystemModstamp", "MasterRecordId",
        }

        fields: list[SourceFieldInfo] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{sf_api}/sobjects/{sf_object}/describe",
                headers=headers,
            )
            if resp.status_code != 200:
                raise ValueError(f"Salesforce describe failed for {sf_object}: {resp.status_code} {resp.text[:200]}")

            describe = resp.json()

            for sf_field in describe.get("fields", []):
                if sf_field.get("deprecatedAndHidden"):
                    continue
                if sf_field["name"] in SYSTEM_FIELDS:
                    continue

                sf_type = sf_field.get("type", "")
                if sf_type not in USEFUL_TYPES:
                    continue

                fields.append(SourceFieldInfo(
                    name=sf_field["name"],
                    label=sf_field.get("label", sf_field["name"]),
                    category="vacancy",
                    sf_type=sf_type,
                ))

        logger.info(f"Discovered {len(fields)} fields from Salesforce object {sf_object}")
        return fields

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

    # Credential fields that should be shown in full (not masked)
    UNMASKED_FIELDS = {"instance_url"}

    @staticmethod
    def _mask_value(value: str, field_name: str) -> str:
        """Create a masked preview of a credential value for admin verification."""
        if not value:
            return ""
        # Some fields are safe to show in full
        if field_name in IntegrationService.UNMASKED_FIELDS:
            return value
        # For short values (< 8 chars), just show dots
        if len(value) < 8:
            return "••••••••"
        # Show last 4 chars
        return f"••••••••{value[-4:]}"

    @staticmethod
    def _build_connection_response(row: asyncpg.Record) -> ConnectionResponse:
        credentials = row["credentials"]
        if isinstance(credentials, str):
            credentials = json.loads(credentials)

        has_credentials = bool(credentials and credentials != {})

        # Build masked credential hints
        credential_hints = {}
        if has_credentials and isinstance(credentials, dict):
            for key, val in credentials.items():
                if isinstance(val, str) and val:
                    credential_hints[key] = IntegrationService._mask_value(val, key)

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
            credential_hints=credential_hints,
            health_status=row["health_status"],
            last_health_check_at=row["last_health_check_at"],
            settings=json.loads(row["settings"]) if isinstance(row["settings"], str) else row["settings"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
