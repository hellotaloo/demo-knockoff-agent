"""
Enums for Taloo Backend API.
"""
from enum import Enum


class VacancyStatus(str, Enum):
    NEW = "new"
    DRAFT = "draft"
    SCREENING_ACTIVE = "screening_active"
    ARCHIVED = "archived"


class VacancySource(str, Enum):
    SALESFORCE = "salesforce"
    BULLHORN = "bullhorn"
    MANUAL = "manual"


class InterviewChannel(str, Enum):
    VOICE = "voice"
    WHATSAPP = "whatsapp"
