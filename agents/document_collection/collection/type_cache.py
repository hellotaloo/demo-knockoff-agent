"""
TypeCache — dynamic type loading from DB for the collection agent.

Loads all document and attribute type definitions for a workspace once,
then serves fast lookups by slug. The agent uses this to get field specs,
ai_hints, scan_mode, etc. at runtime instead of baking them into the plan.
"""

import json
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class TypeCache:
    """Loads all doc/attr types for a workspace once, serves lookups by slug."""

    def __init__(self, pool, workspace_id: uuid.UUID):
        self.pool = pool
        self.workspace_id = workspace_id
        self._doc_types: dict[str, dict] = {}
        self._attr_types: dict[str, dict] = {}
        self._loaded = False

    async def ensure_loaded(self):
        if self._loaded:
            return

        from src.repositories.candidate_attribute_type_repo import CandidateAttributeTypeRepository
        from src.repositories.document_type_repo import DocumentTypeRepository

        attr_repo = CandidateAttributeTypeRepository(self.pool)
        doc_repo = DocumentTypeRepository(self.pool)

        attr_rows = await attr_repo.list_for_workspace(self.workspace_id)
        for row in attr_rows:
            fields = row["fields"]
            if isinstance(fields, str):
                fields = json.loads(fields)
            self._attr_types[row["slug"]] = {
                "slug": row["slug"],
                "name": row["name"],
                "data_type": row["data_type"],
                "fields": fields,
                "ai_hint": row["ai_hint"],
                "category": row["category"],
            }

        doc_rows = await doc_repo.list_for_workspace(self.workspace_id)
        for row in doc_rows:
            verification_config = row["verification_config"]
            if isinstance(verification_config, str):
                verification_config = json.loads(verification_config)
            self._doc_types[row["slug"]] = {
                "slug": row["slug"],
                "name": row["name"],
                "requires_front_back": row["requires_front_back"],
                "is_verifiable": row["is_verifiable"],
                "scan_mode": row["scan_mode"],
                "verification_config": verification_config,
                "ai_hint": row["ai_hint"],
                "category": row["category"],
            }

        self._loaded = True
        logger.info(
            f"TypeCache loaded: {len(self._attr_types)} attr types, "
            f"{len(self._doc_types)} doc types for workspace {self.workspace_id}"
        )

    def get_doc_type(self, slug: str) -> Optional[dict]:
        return self._doc_types.get(slug)

    def get_attr_type(self, slug: str) -> Optional[dict]:
        return self._attr_types.get(slug)

    def get_doc_types_summary(self, slugs: list[str]) -> list[dict]:
        """Return [{slug, name}] for the given slugs — used as classification hints."""
        result = []
        for slug in slugs:
            dt = self._doc_types.get(slug)
            if dt:
                result.append({"slug": dt["slug"], "name": dt["name"]})
        return result


class MockTypeCache:
    """For offline testing (chat.py) with hardcoded type definitions."""

    def __init__(self):
        self._doc_types: dict[str, dict] = {}
        self._attr_types: dict[str, dict] = {}
        self._populate()

    def _populate(self):
        # ── Attribute types ──────────────────────────────────────────────
        self._attr_types = {
            "domicile_address": {
                "slug": "domicile_address",
                "name": "Domicilie adres",
                "data_type": "structured",
                "fields": [
                    {"key": "street", "type": "text", "label": "Straat", "required": True},
                    {"key": "number", "type": "text", "label": "Nummer", "required": True},
                    {"key": "stad", "type": "text", "label": "Stad", "required": True},
                    {"key": "postcode", "type": "text", "label": "Postcode", "required": True},
                    {"key": "country", "type": "text", "label": "Land", "required": False},
                ],
                "ai_hint": "Als stad en/of postcode opgegeven zijn, mag je het land automatisch invullen.",
                "category": "general",
            },
            "adres_gelijk_aan_domicilie": {
                "slug": "adres_gelijk_aan_domicilie",
                "name": "Verblijfsadres gelijk aan domicilie",
                "data_type": "boolean",
                "fields": None,
                "ai_hint": 'Vraag direct na het domicilieadres: "Is je verblijfsadres hetzelfde als je domicilieadres?"',
                "category": "general",
            },
            "verblijfs_adres": {
                "slug": "verblijfs_adres",
                "name": "Verblijfsadres",
                "data_type": "structured",
                "fields": [
                    {"key": "street", "type": "text", "label": "Straat", "required": True},
                    {"key": "number", "type": "text", "label": "Nummer", "required": True},
                    {"key": "stad", "type": "text", "label": "Stad", "required": True},
                    {"key": "postcode", "type": "text", "label": "Postcode", "required": True},
                    {"key": "country", "type": "text", "label": "Land", "required": False},
                ],
                "ai_hint": "Als stad en postcode gekend zijn, vul dan automatisch het land in.",
                "category": "general",
            },
            "has_own_transport": {
                "slug": "has_own_transport",
                "name": "Eigen vervoer",
                "data_type": "boolean",
                "fields": None,
                "ai_hint": "Alleen vragen als vacature vervoer vereist, werklocatie moeilijk bereikbaar, of bij ploegwerk.",
                "category": "general",
            },
            "marital_status": {
                "slug": "marital_status",
                "name": "Burgerlijke staat",
                "data_type": "text",
                "fields": None,
                "ai_hint": "Verzamelen bij contract-fase. Nodig voor Dimona.",
                "category": "general",
            },
            "iban": {
                "slug": "iban",
                "name": "Bankrekeningnummer",
                "data_type": "text",
                "fields": None,
                "ai_hint": "Aan kandidaat vragen. Nodig voor loonuitbetaling. Indien IBAN niet SEPA, flag dit.",
                "category": "general",
            },
            "emergency_contact": {
                "slug": "emergency_contact",
                "name": "Noodcontact",
                "data_type": "structured",
                "fields": [
                    {"key": "name", "type": "text", "label": "Naam", "required": True},
                    {"key": "phone", "type": "phone", "label": "Gsm nummer", "required": True},
                ],
                "ai_hint": "Aan kandidaat vragen.",
                "category": "general",
            },
            "date_of_birth": {
                "slug": "date_of_birth",
                "name": "Geboortedatum",
                "data_type": "date",
                "fields": None,
                "ai_hint": "Af te lezen van identiteitsdocument.",
                "category": "general",
            },
            "nationality": {
                "slug": "nationality",
                "name": "Nationaliteit",
                "data_type": "text",
                "fields": None,
                "ai_hint": "Af te lezen van identiteitsdocument. Bepaalt of werkvergunning nodig is.",
                "category": "general",
            },
            "national_register_nr": {
                "slug": "national_register_nr",
                "name": "Rijksregisternummer",
                "data_type": "text",
                "fields": None,
                "ai_hint": "Af te lezen van identiteitsdocument.",
                "category": "general",
            },
            "work_eligibility": {
                "slug": "work_eligibility",
                "name": "Arbeidstoegang België",
                "data_type": "boolean",
                "fields": None,
                "ai_hint": "Wordt afgeleid uit identiteitsdocumenten.",
                "category": "general",
            },
        }

        # ── Document types ───────────────────────────────────────────────
        self._doc_types = {
            "id_card": {
                "slug": "id_card",
                "name": "ID-kaart",
                "requires_front_back": True,
                "is_verifiable": True,
                "scan_mode": "front_back",
                "verification_config": None,
                "ai_hint": None,
                "category": "identity",
            },
            "passport": {
                "slug": "passport",
                "name": "Paspoort",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "identity",
            },
            "prato_1": {
                "slug": "prato_1",
                "name": "Basisveiligheid VCA",
                "requires_front_back": False,
                "is_verifiable": False,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "certificate",
            },
            "diploma": {
                "slug": "diploma",
                "name": "Diploma/Certificaat",
                "requires_front_back": False,
                "is_verifiable": False,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "certificate",
            },
            "cv": {
                "slug": "cv",
                "name": "CV / Curriculum Vitae",
                "requires_front_back": False,
                "is_verifiable": False,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "other",
            },
            "prato_5": {
                "slug": "prato_5",
                "name": "Werkvergunning",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "certificate",
            },
            "prato_101": {
                "slug": "prato_101",
                "name": "Verblijfsdocument - vrijstelling arbeidskaart",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "identity",
            },
            "prato_102": {
                "slug": "prato_102",
                "name": "Verblijfsdocument - bijkomstige voorwaarden",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "identity",
            },
            "prato_9": {
                "slug": "prato_9",
                "name": "Vrijstelling arbeidskaart",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "certificate",
            },
            "prato_20": {
                "slug": "prato_20",
                "name": "Arbeidskaart",
                "requires_front_back": False,
                "is_verifiable": True,
                "scan_mode": "single",
                "verification_config": None,
                "ai_hint": None,
                "category": "certificate",
            },
        }

    async def ensure_loaded(self):
        pass  # Already populated

    def get_doc_type(self, slug: str) -> Optional[dict]:
        return self._doc_types.get(slug)

    def get_attr_type(self, slug: str) -> Optional[dict]:
        return self._attr_types.get(slug)

    def get_doc_types_summary(self, slugs: list[str]) -> list[dict]:
        """Return [{slug, name}] for the given slugs — used as classification hints."""
        result = []
        for slug in slugs:
            dt = self._doc_types.get(slug)
            if dt:
                result.append({"slug": dt["slug"], "name": dt["name"]})
        return result
