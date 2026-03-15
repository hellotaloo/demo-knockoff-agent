"""
Shared Google service account credential loader.

Supports two modes:
1. File-based (local dev): GOOGLE_SERVICE_ACCOUNT_FILE env var pointing to JSON key file
2. JSON string (Cloud Run): GOOGLE_SERVICE_ACCOUNT_INFO env var containing the JSON key content
"""

import json
import os
import logging

from google.oauth2 import service_account

logger = logging.getLogger(__name__)


def get_service_account_credentials(
    scopes: list[str],
    subject: str | None = None,
) -> service_account.Credentials:
    """
    Load Google service account credentials from file or environment variable.

    Args:
        scopes: OAuth2 scopes to request
        subject: Email to impersonate via domain-wide delegation

    Returns:
        google.oauth2.service_account.Credentials
    """
    service_account_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    service_account_info = os.environ.get("GOOGLE_SERVICE_ACCOUNT_INFO")

    if service_account_file:
        credentials = service_account.Credentials.from_service_account_file(
            service_account_file,
            scopes=scopes,
            subject=subject,
        )
        logger.info(f"Loaded Google credentials from file (impersonating: {subject or 'none'})")
        return credentials

    if service_account_info:
        info = json.loads(service_account_info)
        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=scopes,
            subject=subject,
        )
        logger.info(f"Loaded Google credentials from env var (impersonating: {subject or 'none'})")
        return credentials

    raise RuntimeError(
        "Google service account not configured. "
        "Set GOOGLE_SERVICE_ACCOUNT_FILE (path to JSON key) or "
        "GOOGLE_SERVICE_ACCOUNT_INFO (JSON key content as string)."
    )
