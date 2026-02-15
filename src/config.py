"""
Configuration module for Taloo Backend.
Centralizes environment variables, logging setup, and constants.
"""
import os
import logging
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

# ============================================================================
# External Service Configuration
# ============================================================================

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.environ.get("TWILIO_WHATSAPP_NUMBER")  # e.g., "whatsapp:+14155238886"
TWILIO_MESSAGING_SERVICE_SID = os.environ.get("TWILIO_MESSAGING_SERVICE_SID")  # e.g., "MGxxxxxxxx"

# ElevenLabs Configuration
ELEVENLABS_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")
ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")  # Master voice agent ID

# VAPI Configuration
VAPI_API_KEY = os.environ.get("VAPI_API_KEY")
VAPI_SQUAD_ID = os.environ.get("VAPI_SQUAD_ID", "c43899f8-59fa-4886-85d6-02bed3ed325d")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID")
VAPI_WEBHOOK_SECRET = os.environ.get("VAPI_WEBHOOK_SECRET", "")
VAPI_SERVER_URL = os.environ.get("VAPI_SERVER_URL")  # Webhook URL for this environment

# =============================================================================
# Supabase Auth Configuration
# =============================================================================

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000")

# ============================================================================
# Logging Configuration
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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
