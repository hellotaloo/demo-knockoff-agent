"""
Configuration module for Taloo Backend.
Centralizes environment variables, logging setup, and constants.
"""
import os
import json
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

# ============================================================================
# Environment Configuration
# ============================================================================

# Environment identifier (production, staging, development, etc.)
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production")

# ============================================================================
# Database Configuration
# ============================================================================

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is required")

# =============================================================================
# Supabase Auth Configuration
# =============================================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# ============================================================================
# Twilio Configuration (WhatsApp)
# ============================================================================

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")
TWILIO_MESSAGING_SERVICE_SID = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION = os.environ.get("TWILIO_TEMPLATE_INTERVIEW_CONFIRMATION")
TWILIO_TEMPLATE_INITIATE_PRE_SCREENING = os.environ.get("TWILIO_TEMPLATE_INITIATE_PRE_SCREENING")
TWILIO_TEMPLATE_HEALTH_ALERT = os.environ.get("TWILIO_TEMPLATE_HEALTH_ALERT")

# ============================================================================
# ElevenLabs Configuration (webhook validation only)
# ============================================================================

ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")

# ============================================================================
# LiveKit Configuration (Voice Agent Infrastructure)
# ============================================================================

LIVEKIT_URL = os.environ.get("LIVEKIT_URL")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET")
SIP_OUTBOUND_TRUNK_ID = os.environ.get("SIP_OUTBOUND_TRUNK_ID")
LIVEKIT_AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "pre-screening")
LIVEKIT_WEBHOOK_SECRET = os.environ.get("LIVEKIT_WEBHOOK_SECRET", "")
BACKEND_WEBHOOK_URL = os.environ.get("BACKEND_WEBHOOK_URL", "")

# ============================================================================
# Yousign Configuration (E-Signatures)
# ============================================================================

YOUSIGN_API_KEY = os.environ.get("YOUSIGN_API_KEY", "")
YOUSIGN_WEBHOOK_SECRET = os.environ.get("YOUSIGN_WEBHOOK_SECRET", "")
YOUSIGN_CUSTOM_EXPERIENCE_ID = os.environ.get("YOUSIGN_CUSTOM_EXPERIENCE_ID", "")

# ============================================================================
# Prato Flex Configuration (Workforce Management)
# ============================================================================

PRATO_FLEX_API_URL = os.environ.get("PRATO_FLEX_API_URL", "https://salesdemo.prato.be/webservice")
PRATO_FLEX_API_TOKEN = os.environ.get("PRATO_FLEX_API_TOKEN", "")

# =============================================================================
# Email Configuration (Resend)
# =============================================================================

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM_ADDRESS = os.environ.get("EMAIL_FROM_ADDRESS", "welkom@taloo.eu")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Taloo")

# ============================================================================
# Health Alert Configuration
# ============================================================================

ALERT_WHATSAPP_NUMBER = os.environ.get("ALERT_WHATSAPP_NUMBER")
HEALTH_CHECK_INTERVAL = int(os.environ.get("HEALTH_CHECK_INTERVAL", "300"))
ALERT_COOLDOWN = int(os.environ.get("ALERT_COOLDOWN", "3600"))

# ============================================================================
# ATS Simulator Configuration
# ============================================================================

ATS_SIMULATOR_URL = os.environ.get("ATS_SIMULATOR_URL", "http://localhost:8080/ats-simulator")

# ============================================================================
# Logging Configuration
# ============================================================================


class CloudRunFormatter(logging.Formatter):
    """JSON formatter compatible with Google Cloud Logging.

    Cloud Logging parses the 'severity' field automatically for log levels
    and 'timestamp' for accurate timing.
    """

    def format(self, record):
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "module": record.module,
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


if ENVIRONMENT == "local":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
else:
    handler = logging.StreamHandler()
    handler.setFormatter(CloudRunFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])

logger = logging.getLogger(__name__)

# =============================================================================
# Startup Validation
# =============================================================================


def _validate_env():
    """Validate environment variables at startup. Fail fast on missing required vars."""
    missing_required = []
    missing_optional = []

    # Required — app cannot function without these
    required = {
        "DATABASE_URL": DATABASE_URL,
        "GOOGLE_API_KEY": os.environ.get("GOOGLE_API_KEY"),
        "SUPABASE_URL": SUPABASE_URL,
        "SUPABASE_JWT_SECRET": SUPABASE_JWT_SECRET,
    }
    for name, value in required.items():
        if not value:
            missing_required.append(name)

    # Optional but important — warn if missing so it's obvious what's disabled
    optional_groups = {
        "Twilio (WhatsApp)": {
            "TWILIO_ACCOUNT_SID": TWILIO_ACCOUNT_SID,
            "TWILIO_AUTH_TOKEN": TWILIO_AUTH_TOKEN,
            "TWILIO_WHATSAPP_NUMBER": TWILIO_WHATSAPP_NUMBER,
        },
"LiveKit (Voice Agent)": {
            "LIVEKIT_URL": LIVEKIT_URL,
            "LIVEKIT_API_KEY": LIVEKIT_API_KEY,
            "LIVEKIT_API_SECRET": LIVEKIT_API_SECRET,
        },
        "Resend (Email)": {
            "RESEND_API_KEY": RESEND_API_KEY,
        },
    }

    for group_name, vars_dict in optional_groups.items():
        group_missing = [name for name, value in vars_dict.items() if not value]
        if group_missing:
            missing_optional.append(f"  {group_name}: {', '.join(group_missing)}")

    if missing_required:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing_required)}. "
            f"Check your .env file or Cloud Run configuration."
        )

    if missing_optional:
        logger.warning(
            "Some optional environment variables are not set. "
            "Related features will be disabled:\n%s",
            "\n".join(missing_optional),
        )


_validate_env()

# =============================================================================
# Super Admin Configuration
# =============================================================================

# Email domains that grant super admin access (bypass workspace membership)
SUPER_ADMIN_DOMAINS = [d.strip() for d in os.environ.get("SUPER_ADMIN_DOMAINS", "taloo.eu").split(",")]

# ============================================================================
# Application Constants
# ============================================================================

# Keywords for detecting simple edit operations in interview feedback
SIMPLE_EDIT_KEYWORDS = [
    "verwijder", "delete",  # delete
    "korter", "kort",  # shorter
    "herformuleer",  # rephrase
    "verplaats", "zet",  # move/reorder
    "wijzig", "aanpas", "pas aan",  # change/adjust
    "voeg toe", "toevoeg",  # add (simple additions)
    "goedkeur", "approve",  # approve
]

# Simulated reasoning messages during interview generation
# ~20 seconds total (13 messages × 1.5s interval)
SIMULATED_REASONING = [
    "Vacaturetekst ontvangen, begin met analyse...",
    "Kernvereisten identificeren uit de functieomschrijving...",
    "Zoeken naar harde eisen: werkvergunning, locatie, beschikbaarheid...",
    "Ploegensysteem of flexibele uren detecteren...",
    "Fysieke vereisten en werkomstandigheden analyseren...",
    "Relevante ervaring en competenties in kaart brengen...",
    "Knockout criteria formuleren op basis van must-haves...",
    "Kwalificatievragen opstellen voor ervaring en motivatie...",
    "Vraagvolgorde bepalen voor optimale gespreksstroom...",
    "Interview structuur optimaliseren voor WhatsApp/voice...",
    "Vragen afstemmen op best-practices voor screening...",
    "Toon en woordkeuze verfijnen...",
    "Vragen afronden en valideren...",
]
