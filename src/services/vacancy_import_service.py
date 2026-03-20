"""
Vacancy Import Service.

Provider-agnostic service that imports vacancies from an external ATS
into the local database. The provider layer (ConnexysProvider, etc.)
handles fetching raw records; this service handles field mapping,
transformation, and upserting into ats.vacancies.

Uses a background task pattern: POST starts the sync, GET polls for progress.
"""
import json
import logging
import re
from datetime import date
from typing import Optional
from uuid import UUID

import asyncpg

from src.services.providers import ATSProvider, get_provider
from src.services.integration_service import PROVIDER_MAPPING_CONFIG

logger = logging.getLogger(__name__)

# Regex to extract {{field}} placeholders from mapping templates
TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


# ---------------------------------------------------------------------------
# In-memory sync progress (module-level singleton)
# ---------------------------------------------------------------------------

_sync_progress: dict | None = None


def get_sync_progress() -> dict | None:
    """Return current sync progress, or None if no sync has run."""
    return _sync_progress


def clear_sync_progress():
    """Clear sync progress."""
    global _sync_progress
    _sync_progress = None


def _reset_progress():
    """Reset progress to initial state."""
    global _sync_progress
    _sync_progress = {
        "status": "syncing",
        "message": "Vacatures ophalen...",
        "total_fetched": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
    }


def _set_progress_error(message: str):
    global _sync_progress
    if _sync_progress is None:
        _sync_progress = {}
    _sync_progress["status"] = "error"
    _sync_progress["message"] = message


def _set_progress_complete():
    global _sync_progress
    if _sync_progress is None:
        return
    _sync_progress["status"] = "complete"
    _sync_progress["message"] = (
        f"Sync voltooid: {_sync_progress['inserted']} nieuw, "
        f"{_sync_progress['updated']} bijgewerkt, "
        f"{_sync_progress['skipped']} overgeslagen"
    )


class VacancyImportService:
    """Provider-agnostic vacancy import service."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def sync(self, workspace_id: UUID) -> None:
        """
        Main sync entry point. Runs as a background task.

        1. Find active ATS connection for workspace
        2. Resolve provider + mapping
        3. Fetch raw records via provider
        4. Transform and upsert each record
        """
        _reset_progress()

        try:
            # Load the active ATS connection
            connection = await self._get_active_connection(workspace_id)
            if not connection:
                _set_progress_error("Geen actieve integratie gevonden voor deze workspace")
                return

            provider_slug = connection["slug"]
            credentials = json.loads(connection["credentials"]) if isinstance(connection["credentials"], str) else connection["credentials"]
            settings = json.loads(connection["settings"]) if isinstance(connection["settings"], str) else (connection["settings"] or {})

            # Resolve the field mapping (custom or default)
            mapping = self._get_active_mapping(settings, provider_slug)

            # Get provider and fetch records
            provider: ATSProvider = get_provider(provider_slug)
            _update_progress(message="Vacatures ophalen van extern systeem...")

            raw_records = await provider.fetch_vacancies(credentials, settings, mapping)
            _update_progress(total_fetched=len(raw_records), message=f"{len(raw_records)} vacatures opgehaald, importeren...")

            # Transform and upsert each record
            async with self.pool.acquire() as conn:
                office_location_id = await self._get_default_office_location_id(conn, workspace_id)

                for record in raw_records:
                    try:
                        vacancy_data = self._transform_record(record, mapping)

                        # Filter: skip if sync_filter is explicitly false
                        sync_filter = vacancy_data.pop("sync_filter", None)
                        if sync_filter is False:
                            _update_progress(skipped=(_sync_progress or {}).get("skipped", 0) + 1)
                            continue

                        # Ensure recruiter exists
                        recruiter_id = None
                        recruiter_email = vacancy_data.pop("recruiter_email", None)
                        if recruiter_email:
                            recruiter_id = await self._ensure_recruiter(conn, workspace_id, recruiter_email)

                        # Ensure client exists
                        client_id = None
                        company = vacancy_data.get("company")
                        if company:
                            client_id = await self._ensure_client(conn, workspace_id, company)

                        # Upsert the vacancy
                        action = await self._upsert_vacancy(
                            conn, workspace_id, provider_slug,
                            vacancy_data, recruiter_id, client_id, office_location_id,
                        )

                        if action == "inserted":
                            _update_progress(inserted=(_sync_progress or {}).get("inserted", 0) + 1)
                        elif action == "updated":
                            _update_progress(updated=(_sync_progress or {}).get("updated", 0) + 1)

                    except Exception as e:
                        logger.error(f"Failed to import record {record.get('Id', '?')}: {e}")
                        _update_progress(failed=(_sync_progress or {}).get("failed", 0) + 1)

            _set_progress_complete()

        except Exception as e:
            logger.error(f"Vacancy sync failed: {e}", exc_info=True)
            _set_progress_error(f"Sync mislukt: {str(e)}")

    # =========================================================================
    # Connection & Mapping
    # =========================================================================

    async def _get_active_connection(self, workspace_id: UUID) -> Optional[asyncpg.Record]:
        """Find the active ATS integration connection for this workspace."""
        return await self.pool.fetchrow("""
            SELECT
                ic.id, ic.credentials, ic.settings,
                i.slug
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1
              AND ic.is_active = true
              AND i.slug != 'microsoft'
            LIMIT 1
        """, workspace_id)

    @staticmethod
    def _get_active_mapping(settings: dict, provider_slug: str) -> dict:
        """Get the active field mapping: custom from settings, or provider default."""
        custom = settings.get("field_mapping", {}).get("mappings")
        if custom:
            return custom
        config = PROVIDER_MAPPING_CONFIG.get(provider_slug, {})
        return config.get("default_mapping", {})

    # =========================================================================
    # Field Mapping & Transformation
    # =========================================================================

    @staticmethod
    def _resolve_template(template: str, record: dict) -> str:
        """
        Resolve {{Field.Name}} placeholders from a record dict.

        Handles nested fields like Owner.Email by traversing the dict.
        Returns empty string for None values.
        """
        def replacer(match):
            field_path = match.group(1)
            value = _get_nested_value(record, field_path)
            return str(value) if value is not None else ""
        return TEMPLATE_PATTERN.sub(replacer, template).strip()

    @classmethod
    def _transform_record(cls, record: dict, mapping: dict) -> dict:
        """
        Apply the full field mapping to a raw record.

        Returns a dict with keys matching Taloo vacancy fields.
        Handles type coercion for dates and booleans.
        """
        result = {}
        for target_field, config in mapping.items():
            template = config.get("template", "")
            if not template:
                continue
            value = cls._resolve_template(template, record)
            result[target_field] = value

        # Type coercion
        if "start_date" in result:
            result["start_date"] = _parse_date(result["start_date"])
        if "sync_filter" in result:
            result["sync_filter"] = _parse_boolean(result["sync_filter"])
        if "is_online" in result:
            result["is_online"] = _parse_boolean(result["is_online"])

        return result

    # =========================================================================
    # Database Operations
    # =========================================================================

    @staticmethod
    async def _upsert_vacancy(
        conn: asyncpg.Connection,
        workspace_id: UUID,
        source: str,
        data: dict,
        recruiter_id: Optional[UUID],
        client_id: Optional[UUID],
        office_location_id: Optional[UUID],
    ) -> str:
        """
        Insert or update a vacancy by source + source_id.

        Returns "inserted" or "updated".
        """
        source_id = data.get("source_id")
        if not source_id:
            raise ValueError("source_id is required for vacancy upsert")

        existing = await conn.fetchrow(
            "SELECT id FROM ats.vacancies WHERE source = $1 AND source_id = $2 AND workspace_id = $3",
            source, source_id, workspace_id,
        )

        if existing:
            await conn.execute("""
                UPDATE ats.vacancies SET
                    title = $2, company = $3, location = $4, description = $5,
                    start_date = $6, recruiter_id = $7, client_id = $8,
                    updated_at = now()
                WHERE id = $1
            """,
                existing["id"],
                data.get("title"), data.get("company"), data.get("location"),
                data.get("description"), data.get("start_date"),
                recruiter_id, client_id,
            )
            return "updated"
        else:
            row = await conn.fetchrow("""
                INSERT INTO ats.vacancies
                    (title, company, location, description, status, source, source_id,
                     start_date, recruiter_id, client_id, workspace_id, office_location_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING id
            """,
                data.get("title"), data.get("company"), data.get("location"),
                data.get("description"), "open", source, source_id,
                data.get("start_date"), recruiter_id, client_id,
                workspace_id, office_location_id,
            )

            # Register default agents for new vacancies
            await conn.execute("""
                INSERT INTO ats.vacancy_agents (vacancy_id, agent_type, is_online)
                VALUES ($1, 'document_collection', true)
                ON CONFLICT (vacancy_id, agent_type) DO NOTHING
            """, row["id"])

            return "inserted"

    @staticmethod
    async def _ensure_recruiter(
        conn: asyncpg.Connection, workspace_id: UUID, email: str, name: Optional[str] = None,
    ) -> UUID:
        """Lookup recruiter by email, or create if not found."""
        existing = await conn.fetchrow(
            "SELECT id FROM ats.recruiters WHERE email = $1", email,
        )
        if existing:
            return existing["id"]

        row = await conn.fetchrow("""
            INSERT INTO ats.recruiters (name, email, is_active)
            VALUES ($1, $2, true)
            RETURNING id
        """, name or email, email)
        return row["id"]

    @staticmethod
    async def _ensure_client(
        conn: asyncpg.Connection, workspace_id: UUID, company_name: str,
    ) -> UUID:
        """Lookup client by name, or create if not found."""
        existing = await conn.fetchrow(
            "SELECT id FROM ats.clients WHERE name = $1 AND workspace_id = $2",
            company_name, workspace_id,
        )
        if existing:
            return existing["id"]

        row = await conn.fetchrow("""
            INSERT INTO ats.clients (name, workspace_id)
            VALUES ($1, $2)
            RETURNING id
        """, company_name, workspace_id)
        return row["id"]

    @staticmethod
    async def _get_default_office_location_id(conn: asyncpg.Connection, workspace_id: UUID) -> Optional[UUID]:
        """Look up the default office location for a workspace."""
        row = await conn.fetchrow(
            "SELECT id FROM ats.office_locations WHERE workspace_id = $1 AND is_default = true LIMIT 1",
            workspace_id,
        )
        return row["id"] if row else None


# =============================================================================
# Helpers
# =============================================================================

def _get_nested_value(record: dict, field_path: str):
    """Resolve a dotted field path like 'Owner.Email' from a nested dict."""
    parts = field_path.split(".")
    current = record
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _parse_date(value: str) -> Optional[date]:
    """Parse an ISO date string to a date object. Returns None on failure."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _parse_boolean(value) -> Optional[bool]:
    """Parse a boolean value from various representations."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


def _update_progress(**kwargs):
    """Update specific fields in the sync progress dict."""
    global _sync_progress
    if _sync_progress is None:
        return
    _sync_progress.update(kwargs)
