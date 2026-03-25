"""
Connexys (Salesforce) ATS provider.

Handles Salesforce OAuth2 authentication, SOQL query building,
and paginated record fetching from the Connexys vacancy object.
"""
import logging
import re

import httpx

from src.services.providers import ATSProvider
from src.services.integration_service import CONNEXYS_DEFAULT_SF_OBJECT

logger = logging.getLogger(__name__)

# Regex to extract {{field}} placeholders from mapping templates
TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")

# Connexys vacancy statuses that should be synced
SYNC_STATUSES = [
    "Nieuwe",
    "Instroomvacature",
    "On hold",
    "Ingevuld (ITZU)",
    "Ingevuld (klant)",
    "Ingevuld (concurrent)",
    "Heropend",
]


class ConnexysProvider(ATSProvider):
    """Fetches vacancy records from Connexys via the Salesforce REST API."""

    async def fetch_vacancies(
        self, credentials: dict, settings: dict, mapping: dict,
        since: str | None = None,
    ) -> list[dict]:
        """
        Authenticate to Salesforce, build a SOQL query from the mapping,
        and fetch all matching vacancy records with pagination.

        Args:
            since: ISO datetime string — only fetch records modified after this time.
        """
        access_token, instance_url = await self._get_token(credentials)
        sf_object = settings.get("sf_object", CONNEXYS_DEFAULT_SF_OBJECT)

        # Use cached discovered fields to filter out non-existent fields
        valid_fields = self._get_valid_fields(settings)
        soql = self._build_soql(mapping, sf_object, valid_fields, since=since)
        logger.info(f"Connexys SOQL: {soql}")
        records = await self._fetch_all_records(access_token, instance_url, soql)
        logger.info(f"Fetched {len(records)} records from Connexys")
        return records

    @staticmethod
    async def _get_token(credentials: dict) -> tuple[str, str]:
        """Authenticate to Salesforce via OAuth2 client_credentials. Returns (token, instance_url)."""
        from src.services.integration_service import IntegrationService
        return await IntegrationService._get_connexys_token(credentials)

    @staticmethod
    def _get_valid_fields(settings: dict) -> set[str] | None:
        """Extract valid field names from the cached field discovery results."""
        field_cache = settings.get("field_cache", {})
        source_fields = field_cache.get("source_fields")
        if not source_fields:
            return None  # No cache — allow all fields (will fail at query time if invalid)
        return {f["name"] for f in source_fields}

    @staticmethod
    def _build_soql(
        mapping: dict, sf_object: str, valid_fields: set[str] | None = None,
        since: str | None = None,
    ) -> str:
        """
        Build a SOQL SELECT from the mapping templates.

        Extracts all {{field}} references, validates against discovered fields,
        and filters by active vacancy statuses.

        Args:
            since: ISO datetime string — adds LastModifiedDate filter for incremental sync.
        """
        # Collect all Salesforce fields referenced in the mapping templates
        fields: set[str] = set()
        for _target, config in mapping.items():
            template = config.get("template", "")
            fields.update(TEMPLATE_PATTERN.findall(template))

        # Always include these for identification and filtering
        fields.update(["Id", "cxsrec__Status__c", "LastModifiedDate"])

        # Filter out fields that don't exist on this Salesforce instance
        if valid_fields is not None:
            # Relationship fields like Owner.Email → base object "Owner" won't be in the flat list,
            # but the dotted name itself might be. Allow relationship fields through.
            invalid = {f for f in fields if "." not in f and f not in valid_fields}
            if invalid:
                logger.warning(f"Skipping unknown Salesforce fields: {invalid}")
                fields -= invalid

        # Build the query
        field_list = ", ".join(sorted(fields))
        status_list = ", ".join(f"'{s}'" for s in SYNC_STATUSES)
        soql = (
            f"SELECT {field_list} "
            f"FROM {sf_object} "
            f"WHERE cxsrec__Status__c IN ({status_list})"
        )

        # Incremental sync: only fetch records modified since last sync
        if since:
            soql += f" AND LastModifiedDate >= {since}"

        soql += " ORDER BY LastModifiedDate ASC"
        return soql

    # =========================================================================
    # Write Operations (Data Push-back)
    # =========================================================================

    async def create_record(self, credentials: dict, sf_object: str, data: dict) -> str:
        """Create a Salesforce record. Returns the new record ID."""
        access_token, instance_url = await self._get_token(credentials)
        url = f"{instance_url}/services/data/v62.0/sobjects/{sf_object}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=data, headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            })

            if resp.status_code not in (200, 201):
                error_body = resp.text[:500]
                logger.error(f"Salesforce create failed for {sf_object} ({resp.status_code}): {error_body}")
                raise ValueError(f"Salesforce create failed ({resp.status_code}): {error_body}")

            result = resp.json()
            record_id = result.get("id")
            logger.info(f"Created {sf_object} record: {record_id}")
            return record_id

    async def update_record(self, credentials: dict, sf_object: str, record_id: str, data: dict) -> None:
        """Update an existing Salesforce record."""
        access_token, instance_url = await self._get_token(credentials)
        url = f"{instance_url}/services/data/v62.0/sobjects/{sf_object}/{record_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(url, json=data, headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            })

            if resp.status_code not in (200, 204):
                error_body = resp.text[:500]
                logger.error(f"Salesforce update failed for {sf_object}/{record_id} ({resp.status_code}): {error_body}")
                raise ValueError(f"Salesforce update failed ({resp.status_code}): {error_body}")

            logger.info(f"Updated {sf_object} record: {record_id}")

    async def upsert_record(
        self, credentials: dict, sf_object: str, external_id_field: str, external_id: str, data: dict
    ) -> str:
        """Upsert a Salesforce record using an external ID field. Returns the record ID."""
        access_token, instance_url = await self._get_token(credentials)
        url = f"{instance_url}/services/data/v62.0/sobjects/{sf_object}/{external_id_field}/{external_id}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.patch(url, json=data, headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            })

            if resp.status_code not in (200, 201, 204):
                error_body = resp.text[:500]
                logger.error(f"Salesforce upsert failed for {sf_object} ({resp.status_code}): {error_body}")
                raise ValueError(f"Salesforce upsert failed ({resp.status_code}): {error_body}")

            # 201 = created (has body with id), 200/204 = updated (may not have body)
            if resp.status_code == 201:
                result = resp.json()
                record_id = result.get("id", "")
            else:
                # For updates, we need to look up the record ID
                record_id = external_id

            logger.info(f"Upserted {sf_object} record via {external_id_field}={external_id}")
            return record_id

    # =========================================================================
    # Read Operations
    # =========================================================================

    @staticmethod
    async def _fetch_all_records(
        access_token: str, instance_url: str, soql: str
    ) -> list[dict]:
        """Fetch all records from Salesforce with pagination."""
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{instance_url}/services/data/v62.0/query"
        params = {"q": soql}
        all_records: list[dict] = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            while True:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    error_body = resp.text[:500]
                    logger.error(f"Salesforce query failed ({resp.status_code}): {error_body}")
                    raise ValueError(f"Salesforce query failed ({resp.status_code}): {error_body}")
                data = resp.json()
                all_records.extend(data.get("records", []))

                if data.get("done", True):
                    break

                # Follow pagination URL
                next_url = data.get("nextRecordsUrl")
                if not next_url:
                    break
                url = f"{instance_url}{next_url}"
                params = None  # nextRecordsUrl is a full path

        return all_records
