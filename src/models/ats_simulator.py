"""
ATS Simulator models.

Represents the data shape of an external Applicant Tracking System (e.g., Salesforce).
Intentionally uses different naming conventions to simulate a real integration
where field names and structures differ from internal models.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ATSRecruiter(BaseModel):
    """Recruiter as represented in the external ATS."""
    external_id: str = Field(..., description="ATS-internal recruiter ID")
    full_name: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    department: Optional[str] = None
    job_title: Optional[str] = None
    photo_url: Optional[str] = None
    active: bool = True


class ATSClient(BaseModel):
    """Client/company as represented in the external ATS."""
    external_id: str = Field(..., description="ATS-internal client ID")
    company_name: str
    headquarters: Optional[str] = None
    sector: Optional[str] = None
    logo_url: Optional[str] = None


class ATSVacancy(BaseModel):
    """Vacancy as represented in the external ATS."""
    external_id: str = Field(..., description="ATS-internal vacancy ID, e.g. sf-1633942")
    title: str
    company_name: str
    work_location: Optional[str] = None
    description_html: Optional[str] = None
    status: str = "active"
    created_date: Optional[datetime] = None
    recruiter_email: Optional[str] = None
    client_name: Optional[str] = None


class ATSListResponse(BaseModel):
    """Paginated list response from the ATS."""
    data: list
    total_count: int
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class ATSVacancyListResponse(ATSListResponse):
    data: list[ATSVacancy]


class ATSRecruiterListResponse(ATSListResponse):
    data: list[ATSRecruiter]


class ATSClientListResponse(ATSListResponse):
    data: list[ATSClient]


class ATSImportResult(BaseModel):
    """Result of an ATS import operation."""
    source: str = "ats_simulator"
    recruiters_imported: int = 0
    clients_imported: int = 0
    vacancies_imported: int = 0
    errors: list[str] = []
