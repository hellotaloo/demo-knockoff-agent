"""
Domain rules for document collection.

Contains business logic that is independent of the conversation agent:
- IBAN validation
- Work permit skip rules
- Address ordering and auto-copy logic
- Address geocoding via Google Maps
"""

import logging
import os
import re
from dataclasses import dataclass

import httpx
import phonenumbers

logger = logging.getLogger(__name__)


# ─── IBAN Validation ─────────────────────────────────────────────────────────

# SEPA member country codes (EU + EEA + UK + CH + MC + SM + AD + VA)
SEPA_COUNTRIES = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR",
    "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL",
    "PL", "PT", "RO", "SK", "SI", "ES", "SE",  # EU
    "IS", "LI", "NO",  # EEA
    "CH", "GB", "MC", "SM", "AD", "VA",  # Other SEPA
}


@dataclass
class IbanResult:
    valid: bool
    formatted: str
    country_code: str
    is_sepa: bool
    is_belgian: bool


def validate_iban(raw: str) -> IbanResult:
    """Validate and normalize an IBAN using the mod-97 checksum algorithm."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    country_code = cleaned[:2] if len(cleaned) >= 2 else ""
    formatted = " ".join(cleaned[i:i + 4] for i in range(0, len(cleaned), 4))

    if len(cleaned) < 5:
        return IbanResult(valid=False, formatted=formatted, country_code=country_code, is_sepa=False, is_belgian=False)

    # Move first 4 chars to end, convert letters to digits (A=10, B=11, ...)
    rearranged = cleaned[4:] + cleaned[:4]
    numeric = ""
    for ch in rearranged:
        if ch.isdigit():
            numeric += ch
        else:
            numeric += str(ord(ch) - ord("A") + 10)

    is_valid = int(numeric) % 97 == 1

    return IbanResult(
        valid=is_valid,
        formatted=formatted,
        country_code=country_code,
        is_sepa=country_code in SEPA_COUNTRIES,
        is_belgian=country_code == "BE",
    )


# ─── Phone Number Validation ─────────────────────────────────────────────────

@dataclass
class PhoneResult:
    valid: bool
    formatted: str  # E.164 format (+32...)
    is_belgian: bool


def validate_phone(raw: str) -> PhoneResult:
    """Validate and normalize a phone number, assuming Belgian (+32) if no country code."""
    try:
        parsed = phonenumbers.parse(raw, "BE")
        if phonenumbers.is_valid_number(parsed):
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            return PhoneResult(valid=True, formatted=e164, is_belgian=parsed.country_code == 32)
    except phonenumbers.NumberParseException:
        pass
    return PhoneResult(valid=False, formatted=raw, is_belgian=False)


# ─── Work Permit Rules ──────────────────────────────────────────────────────

# Document slugs that represent work/labour permits — skipped for EU/EER citizens
WORK_PERMIT_SLUGS = {"prato_5", "prato_9", "prato_20", "prato_101", "prato_102"}


def is_work_permit_item(item: dict) -> bool:
    """Check if an item (document or document_group) is a work permit."""
    if item.get("type") == "document_group":
        return all(a["slug"] in WORK_PERMIT_SLUGS for a in item.get("alternatives", []))
    return item.get("slug", "") in WORK_PERMIT_SLUGS


# ─── Address Rules ───────────────────────────────────────────────────────────

# Slugs that form the address collection group (ordered: domicilie → same? → verblijf)
ADDRESS_SLUGS = {"domicile_address", "domicilie_adres", "adres_gelijk_aan_domicilie", "verblijfs_adres"}

# Slugs where geocoding should be used for structured extraction
ADDRESS_GEOCODE_SLUGS = {"domicile_address", "domicilie_adres", "verblijfs_adres"}


async def geocode_address(freetext: str) -> dict | None:
    """
    Parse a freetext address into structured fields using Google Maps Geocoding API.

    Returns a dict with keys matching the address field spec:
      {"street": "...", "number": "...", "stad": "...", "postcode": "...", "country": "..."}
    Returns None if geocoding fails or produces no results.
    """
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("[GEOCODE] No GOOGLE_MAPS_API_KEY or GOOGLE_API_KEY set, skipping geocode")
        return None

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": freetext,
                    "region": "be",
                    "language": "nl",
                    "key": api_key,
                },
            )
            data = resp.json()
    except Exception as e:
        logger.warning(f"[GEOCODE] API call failed: {e}")
        return None

    if data.get("status") != "OK" or not data.get("results"):
        logger.info(f"[GEOCODE] No results for '{freetext}': {data.get('status')}")
        return None

    result = data["results"][0]
    components = {c["types"][0]: c["long_name"] for c in result.get("address_components", []) if c.get("types")}

    street = components.get("route", "")
    number = components.get("street_number", "")
    city = components.get("locality") or components.get("sublocality") or components.get("postal_town", "")
    postcode = components.get("postal_code", "")
    country = components.get("country", "")

    if not street or not number:
        logger.info(f"[GEOCODE] Incomplete address for '{freetext}': street={street!r}, number={number!r}")
        return None

    parsed = {
        "street": street,
        "number": number,
        "stad": city,
        "postcode": postcode,
        "country": country,
    }
    logger.info(f"[GEOCODE] '{freetext}' → {parsed}")
    return parsed


# ─── Task Scheduling ─────────────────────────────────────────────────────────

async def schedule_task(task_slug: str, task_name: str, availability: str, collection_id: str) -> dict:
    """Placeholder for async task scheduling (medical exam, etc.). Returns pending status."""
    logger.info(f"[TASK] Schedule requested: {task_name} ({task_slug}) — availability: {availability}, collection: {collection_id}")
    return {"status": "pending", "message": f"Scheduling {task_name} requested"}
