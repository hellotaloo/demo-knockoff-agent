"""
Demo fixtures for seeding the database.

Edit the JSON files to update demo data:
- candidates.json: Candidate registry
- vacancies.json: Job postings
- applications.json: Candidate interview results
- pre_screenings.json: Pre-screening configurations with questions
"""

import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def load_candidates() -> list[dict]:
    """Load demo candidates from JSON file."""
    with open(FIXTURES_DIR / "candidates.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_vacancies() -> list[dict]:
    """Load demo vacancies from JSON file."""
    with open(FIXTURES_DIR / "vacancies.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_applications() -> list[dict]:
    """Load demo applications from JSON file."""
    with open(FIXTURES_DIR / "applications.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_pre_screenings() -> list[dict]:
    """Load demo pre-screenings from JSON file."""
    with open(FIXTURES_DIR / "pre_screenings.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_recruiters() -> list[dict]:
    """Load demo recruiters from JSON file."""
    with open(FIXTURES_DIR / "recruiters.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_clients() -> list[dict]:
    """Load demo clients from JSON file."""
    with open(FIXTURES_DIR / "clients.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_activities() -> list[dict]:
    """Load demo activities from JSON file."""
    with open(FIXTURES_DIR / "activities.json", "r", encoding="utf-8") as f:
        return json.load(f)
