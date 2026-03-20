"""
Data Push-back Service.

Pushes pre-screening results from Taloo back to the external ATS (e.g. Connexys/Salesforce).
Mirrors the VacancyImportService pattern but reverses the data flow:
  - Source: Taloo application data
  - Target: External ATS fields
  - Mapping: stored in settings.data_pushback.mappings
"""
import json
import logging
import re
from typing import Optional
from uuid import UUID

import asyncpg

from src.models.integrations import PushbackResultResponse
from src.models.application import QuestionAnswerResponse
from src.repositories.application_repo import ApplicationRepository
from src.services.providers import ATSProvider, get_provider
from src.services.integration_service import PROVIDER_EXPORT_CONFIG

logger = logging.getLogger(__name__)

# Regex to extract {{field}} placeholders from mapping templates
TEMPLATE_PATTERN = re.compile(r"\{\{(\w+(?:\.\w+)*)\}\}")


class DataPushbackService:
    """Pushes screening results back to the external ATS."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.app_repo = ApplicationRepository(pool)

    async def push_application(self, application_id: UUID, workspace_id: UUID) -> PushbackResultResponse:
        """Push a single completed application's results back to the ATS."""
        try:
            # 1. Load application + answers
            app_row = await self.app_repo.get_by_id(application_id, workspace_id=workspace_id)
            if not app_row:
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="error",
                    message="Sollicitatie niet gevonden",
                )

            if app_row["status"] != "completed":
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="skipped",
                    message="Sollicitatie is nog niet afgerond",
                )

            answer_rows = await self.app_repo.get_answers(application_id)

            # 2. Load connection + mapping
            connection = await self._get_active_connection(workspace_id)
            if not connection:
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="error",
                    message="Geen actieve ATS-integratie gevonden",
                )

            provider_slug = connection["slug"]
            credentials = json.loads(connection["credentials"]) if isinstance(connection["credentials"], str) else connection["credentials"]
            settings = json.loads(connection["settings"]) if isinstance(connection["settings"], str) else (connection["settings"] or {})

            pushback_settings = settings.get("data_pushback", {})
            if not pushback_settings.get("enabled"):
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="skipped",
                    message="Data terugkoppeling is niet ingeschakeld",
                )

            mapping = pushback_settings.get("mappings", {})
            if not mapping:
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="error",
                    message="Geen veldmapping geconfigureerd voor data terugkoppeling",
                )

            sf_object = pushback_settings.get("sf_object")
            if not sf_object:
                config = PROVIDER_EXPORT_CONFIG.get(provider_slug, {})
                sf_object = config.get("default_sf_object", "cxsrec__cxsCandidate__c")

            # 3. Load vacancy for source_id
            vacancy_row = await self.pool.fetchrow(
                "SELECT source_id FROM ats.vacancies WHERE id = $1",
                app_row["vacancy_id"],
            )

            # 4. Build export record and resolve mapping
            export_record = self._build_export_record(app_row, answer_rows, vacancy_row)
            sf_payload = self._resolve_mapping(mapping, export_record)

            if not sf_payload:
                return PushbackResultResponse(
                    application_id=str(application_id),
                    status="error",
                    message="Veldmapping leverde geen data op om te versturen",
                )

            # 5. Push to ATS
            provider: ATSProvider = get_provider(provider_slug)
            record_id = await provider.create_record(credentials, sf_object, sf_payload)

            # 6. Mark as synced
            await self._mark_synced(application_id)

            return PushbackResultResponse(
                application_id=str(application_id),
                status="success",
                message=f"Data succesvol verstuurd naar {sf_object}",
                sf_record_id=record_id,
            )

        except Exception as e:
            logger.error(f"Push-back failed for application {application_id}: {e}", exc_info=True)
            return PushbackResultResponse(
                application_id=str(application_id),
                status="error",
                message=f"Fout bij versturen: {str(e)}",
            )

    async def push_batch(self, vacancy_id: UUID, workspace_id: UUID) -> list[PushbackResultResponse]:
        """Push all unsynced completed applications for a vacancy."""
        rows = await self.pool.fetch(
            """
            SELECT a.id FROM ats.applications a
            JOIN ats.vacancies v ON v.id = a.vacancy_id
            WHERE a.vacancy_id = $1
              AND v.workspace_id = $2
              AND a.status = 'completed'
              AND a.synced = false
              AND a.is_test = false
            ORDER BY a.completed_at
            """,
            vacancy_id, workspace_id,
        )

        results = []
        for row in rows:
            result = await self.push_application(row["id"], workspace_id)
            results.append(result)

        return results

    # =========================================================================
    # Export Record Building
    # =========================================================================

    @staticmethod
    def _build_export_record(
        app_row: asyncpg.Record,
        answer_rows: list[asyncpg.Record],
        vacancy_row: Optional[asyncpg.Record],
    ) -> dict:
        """Build a flat dict of all exportable Taloo fields from the application data."""
        # Build answers list for formatting
        answers = []
        knockout_passed = 0
        knockout_total = 0
        qual_scores = []

        for row in answer_rows:
            answer = QuestionAnswerResponse(
                question_id=str(row["question_id"]),
                question_text=row["question_text"],
                answer=row["answer"],
                passed=row["passed"],
                score=row["score"],
                rating=row["rating"],
                motivation=row["motivation"],
            )
            answers.append(answer)

            # Determine question type from answer data
            if row["passed"] is not None:
                knockout_total += 1
                if row["passed"]:
                    knockout_passed += 1
            elif row["score"] is not None:
                qual_scores.append(row["score"])

        open_questions_score = round(sum(qual_scores) / len(qual_scores)) if qual_scores else None
        qualified = app_row["qualified"] if app_row["qualified"] is not None else False

        completed_at = app_row["completed_at"]
        completed_at_str = completed_at.isoformat() if completed_at else ""

        return {
            "candidate_name": app_row["candidate_name"] or "",
            "candidate_phone": app_row.get("candidate_phone") or "",
            "candidate_email": app_row.get("candidate_email") or "",
            "summary": app_row["summary"] or "",
            "open_questions_score": str(open_questions_score) if open_questions_score is not None else "",
            "qualified": "true" if qualified else "false",
            "knockout_passed": str(knockout_passed),
            "knockout_total": str(knockout_total),
            "knockout_result": f"{knockout_passed}/{knockout_total}",
            "answers_formatted": DataPushbackService._format_answers(answers),
            "channel": app_row["channel"] or "",
            "interaction_seconds": str(app_row["interaction_seconds"] or 0),
            "interview_slot": app_row["interview_slot"] or "",
            "completed_at": completed_at_str,
            "vacancy_source_id": vacancy_row["source_id"] if vacancy_row else "",
        }

    @staticmethod
    def _format_answers(answers: list[QuestionAnswerResponse]) -> str:
        """Format all Q&A into a readable text block for the ATS."""
        lines = []

        # Knockout questions
        knockout = [a for a in answers if a.passed is not None]
        if knockout:
            lines.append("=== KNOCK-OUT VRAGEN ===\n")
            for a in knockout:
                status = "Geslaagd" if a.passed else "Niet geslaagd"
                lines.append(f"Vraag: {a.question_text}")
                lines.append(f"Antwoord: {a.answer or '-'}")
                lines.append(f"Resultaat: {status}")
                lines.append("")

        # Qualification questions
        qualification = [a for a in answers if a.score is not None]
        if qualification:
            lines.append("=== KWALIFICERENDE VRAGEN ===\n")
            for a in qualification:
                lines.append(f"Vraag: {a.question_text}")
                lines.append(f"Antwoord: {a.answer or '-'}")
                lines.append(f"Score: {a.score}/100 ({a.rating or '-'})")
                if a.motivation:
                    lines.append(f"Motivatie: {a.motivation}")
                lines.append("")

        return "\n".join(lines)

    # =========================================================================
    # Mapping Resolution
    # =========================================================================

    @staticmethod
    def _resolve_template(template: str, record: dict) -> str:
        """Resolve {{field_name}} placeholders from the export record dict."""
        def replacer(match):
            field_name = match.group(1)
            value = record.get(field_name)
            return str(value) if value is not None else ""
        return TEMPLATE_PATTERN.sub(replacer, template).strip()

    @classmethod
    def _resolve_mapping(cls, mapping: dict, record: dict) -> dict:
        """
        Apply the export mapping to build the Salesforce payload.

        Mapping format: { "SF_Field__c": { "template": "{{taloo_field}}" }, ... }
        Returns a dict ready for Salesforce API.
        """
        payload = {}
        for sf_field, config in mapping.items():
            template = config.get("template", "")
            if not template:
                continue
            value = cls._resolve_template(template, record)
            if value:  # Only include non-empty values
                payload[sf_field] = value
        return payload

    # =========================================================================
    # Database Helpers
    # =========================================================================

    async def _get_active_connection(self, workspace_id: UUID) -> Optional[asyncpg.Record]:
        """Find the active ATS integration connection for this workspace."""
        return await self.pool.fetchrow("""
            SELECT
                ic.id, ic.credentials, ic.settings,
                i.slug
            FROM system.integration_connections ic
            JOIN system.integrations i ON i.id = ic.integration_id
            WHERE ic.workspace_id = $1
              AND ic.is_active = true
              AND i.slug != 'microsoft'
            LIMIT 1
        """, workspace_id)

    async def _mark_synced(self, application_id: UUID) -> None:
        """Mark an application as synced to the external ATS."""
        await self.pool.execute(
            """
            UPDATE ats.applications
            SET synced = true, synced_at = NOW()
            WHERE id = $1
            """,
            application_id,
        )
