"""
Application service - handles application listing, creation, and answer merging.
"""
import uuid
from typing import Optional, Tuple
import asyncpg
from src.repositories import ApplicationRepository, CandidateRepository
from src.models import ApplicationResponse, QuestionAnswerResponse


class ApplicationService:
    """Service for application operations."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = ApplicationRepository(pool)
        self.candidate_repo = CandidateRepository(pool)
    
    @staticmethod
    def build_application_response(
        app_row: asyncpg.Record,
        all_questions: list[asyncpg.Record],
        answer_rows: list[asyncpg.Record]
    ) -> ApplicationResponse:
        """
        Build an ApplicationResponse model from database rows.
        
        Merges questions with answers, handling both UUID and legacy (ko_1, qual_2) formats.
        Calculates overall score and question statistics.
        """
        # Build a map of existing answers by question_id
        answer_map = {a["question_id"]: a for a in answer_rows}
        
        answers = []
        total_score = 0
        score_count = 0
        knockout_passed = 0
        knockout_total = 0
        qualification_count = 0
        
        # Process all questions, merging with answers where available
        for q in all_questions:
            q_id = str(q["id"])
            # Check both UUID format and ko_/qual_ prefix format
            existing_answer = answer_map.get(q_id)
            if not existing_answer:
                # Try legacy format (ko_1, qual_2, etc.)
                # Note: position in DB is 0-indexed, but ko_/qual_ IDs are 1-indexed
                if q["question_type"] == "knockout":
                    legacy_id = f"ko_{q['position'] + 1}"
                else:
                    legacy_id = f"qual_{q['position'] + 1}"
                existing_answer = answer_map.get(legacy_id)
            
            if existing_answer:
                answers.append(QuestionAnswerResponse(
                    question_id=existing_answer["question_id"],
                    question_text=existing_answer["question_text"],
                    question_type=q["question_type"],
                    answer=existing_answer["answer"],
                    passed=existing_answer.get("passed"),
                    score=existing_answer.get("score"),
                    rating=existing_answer.get("rating"),
                    motivation=existing_answer.get("motivation")
                ))
                
                # Update statistics
                if q["question_type"] == "knockout":
                    knockout_total += 1
                    if existing_answer.get("passed"):
                        knockout_passed += 1
                else:
                    qualification_count += 1
                    if existing_answer.get("score") is not None:
                        total_score += existing_answer["score"]
                        score_count += 1
        
        # Calculate average score
        avg_score = round(total_score / score_count, 1) if score_count > 0 else None
        
        return ApplicationResponse(
            id=str(app_row["id"]),
            vacancy_id=str(app_row["vacancy_id"]),
            candidate_name=app_row["candidate_name"],
            channel=app_row["channel"],
            status=app_row["status"],
            qualified=app_row["qualified"],
            started_at=app_row["started_at"],
            completed_at=app_row["completed_at"],
            interaction_seconds=app_row["interaction_seconds"],
            synced=app_row["synced"],
            synced_at=app_row["synced_at"],
            summary=app_row["summary"],
            interview_slot=app_row["interview_slot"],
            is_test=app_row["is_test"] or False,
            answers=answers,
            knockout_passed=knockout_passed,
            knockout_total=knockout_total,
            qualification_count=qualification_count,
            avg_score=avg_score
        )
    
    async def list_applications(
        self,
        vacancy_id: uuid.UUID,
        qualified: Optional[bool] = None,
        completed: Optional[bool] = None,
        synced: Optional[bool] = None,
        is_test: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[list[ApplicationResponse], int]:
        """
        List applications for a vacancy with optional filtering.
        
        Returns:
            Tuple of (application list, total count)
        """
        rows, total = await self.repo.list_for_vacancy(
            vacancy_id, qualified, completed, synced, is_test, limit, offset
        )
        
        # For each application, get questions and answers
        applications = []
        for app_row in rows:
            question_rows = await self.repo.get_questions_for_vacancy(app_row["vacancy_id"])
            answer_rows = await self.repo.get_answers(app_row["id"])
            applications.append(
                self.build_application_response(app_row, question_rows, answer_rows)
            )
        
        return applications, total
    
    async def get_application(self, application_id: uuid.UUID) -> Optional[ApplicationResponse]:
        """Get a single application by ID with answers."""
        app_row = await self.repo.get_by_id(application_id)
        if not app_row:
            return None
        
        question_rows = await self.repo.get_questions_for_vacancy(app_row["vacancy_id"])
        answer_rows = await self.repo.get_answers(application_id)
        
        return self.build_application_response(app_row, question_rows, answer_rows)
    
    async def create_application(
        self,
        vacancy_id: uuid.UUID,
        candidate_name: str,
        candidate_phone: Optional[str],
        channel: str,
        is_test: bool = False,
        candidate_email: Optional[str] = None
    ) -> uuid.UUID:
        """Create a new application with linked candidate."""
        # Find or create candidate in central candidates table
        candidate_id = await self.candidate_repo.find_or_create(
            full_name=candidate_name,
            phone=candidate_phone,
            email=candidate_email
        )

        return await self.repo.create(
            vacancy_id=vacancy_id,
            candidate_name=candidate_name,
            candidate_phone=candidate_phone,
            channel=channel,
            is_test=is_test,
            candidate_id=candidate_id
        )
