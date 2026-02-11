"""
Enums for Taloo Backend API.
"""
from enum import Enum


class VacancyStatus(str, Enum):
    """Vacancy lifecycle status (independent of agent/screening config)."""
    CONCEPT = "concept"
    OPEN = "open"
    ON_HOLD = "on_hold"
    FILLED = "filled"
    CLOSED = "closed"


class VacancySource(str, Enum):
    SALESFORCE = "salesforce"
    BULLHORN = "bullhorn"
    MANUAL = "manual"


class InterviewChannel(str, Enum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"
