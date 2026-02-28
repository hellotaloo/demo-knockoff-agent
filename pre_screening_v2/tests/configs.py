"""
Test configuration builder.
Generates SessionInput instances for parameterized testing.
When a new interview is created, update `default_session_input()` —
all tests automatically pick up the new questions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import SessionInput, KnockoutQuestion, OpenQuestion, CandidateRecord


def default_session_input() -> SessionInput:
    """Standard bakery worker configuration."""
    return SessionInput(
        candidate_name="Test Kandidaat",
        candidate_known=False,
        require_consent=False,
        job_title="Bakkerij Medewerker",
        office_location="Antwerpen Centrum",
        office_address="Mechelsesteenweg nummer 27",
        knockout_questions=[
            KnockoutQuestion(
                id="q1",
                text="Mag je wettelijk werken in Belgie?",
                data_key="work_permit",
            ),
            KnockoutQuestion(
                id="q2",
                text="Heb je ervaring met werken in een bakkerij of in de verkoop?",
                data_key="relevant_experience",
            ),
            KnockoutQuestion(
                id="q3",
                text="Ben je beschikbaar om in het weekend te werken?",
                context="2 a 3 weekends per maand is prima.",
                data_key="weekend_available",
            ),
        ],
        open_questions=[
            OpenQuestion(id="oq1", text="Waarom wil je in een bakkerij werken?", description="Motivatievraag"),
            OpenQuestion(id="oq2", text="Wat zijn je sterke punten voor deze functie?", description="Sterke punten"),
            OpenQuestion(id="oq3", text="Wanneer zou je kunnen starten?", description="Beschikbaarheid"),
        ],
        allow_escalation=True,
    )


def known_candidate_input() -> SessionInput:
    """Known candidate with one pre-known answer (work_permit)."""
    inp = default_session_input()
    inp.candidate_name = "Mark Verbeke"
    inp.candidate_known = True
    inp.candidate_record = CandidateRecord(
        known_answers={"work_permit": "ja"},
    )
    return inp


def known_candidate_with_booking_input() -> SessionInput:
    """Known candidate with existing booking — scheduling is skipped."""
    inp = known_candidate_input()
    inp.candidate_record = CandidateRecord(
        known_answers={"work_permit": "ja"},
        existing_booking_date="dinsdag 4 maart om 10 uur",
    )
    return inp


def all_known_answers_input() -> SessionInput:
    """All knockout answers pre-known — screening is skipped entirely."""
    inp = known_candidate_input()
    inp.candidate_record = CandidateRecord(
        known_answers={
            "work_permit": "ja",
            "relevant_experience": "ja",
            "weekend_available": "ja",
        },
    )
    return inp


def consent_enabled_input() -> SessionInput:
    """Configuration with consent recording enabled."""
    inp = default_session_input()
    inp.require_consent = True
    return inp


def no_escalation_input() -> SessionInput:
    """Configuration with escalation disabled."""
    inp = default_session_input()
    inp.allow_escalation = False
    return inp
