"""
Repository layer for data access.
"""
from .vacancy_repo import VacancyRepository
from .application_repo import ApplicationRepository

__all__ = ["VacancyRepository", "ApplicationRepository"]
