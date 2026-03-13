"""
Placement models — tracks a candidate's employment placement.
"""
from datetime import date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class PlacementRegime(str, Enum):
    FULL = "full"
    FLEX = "flex"
    DAY = "day"


class PlacementCreate(BaseModel):
    """Payload sent when a recruiter confirms a placement (offer stage)."""
    candidate_id: str
    vacancy_id: str
    client_id: Optional[str] = None
    start_date: Optional[date] = None
    regime: PlacementRegime = PlacementRegime.FULL
    contract_id: Optional[str] = None
    create_contract: bool = True


class PlacementResponse(BaseModel):
    id: str
    candidate_id: str
    vacancy_id: str
    client_id: Optional[str] = None
    start_date: Optional[date] = None
    regime: Optional[str] = None
    contract_id: Optional[str] = None
    status: str = "proposed"
    created_at: datetime
    updated_at: datetime
