"""
Pre-screening service - handles pre-screening orchestration.
"""
import uuid
from typing import Optional
from datetime import datetime
import asyncpg
from src.repositories import PreScreeningRepository


class PreScreeningService:
    """Service for pre-screening orchestration."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.repo = PreScreeningRepository(pool)
    
    async def save_pre_screening(
        self,
        vacancy_id: uuid.UUID,
        intro: str,
        knockout_failed_action: str,
        final_action: str,
        knockout_questions: list[dict],
        qualification_questions: list[dict],
        approved_ids: list[str]
    ) -> uuid.UUID:
        """
        Save or update pre-screening configuration.
        
        Returns the pre_screening_id.
        """
        return await self.repo.upsert(
            vacancy_id,
            intro,
            knockout_failed_action,
            final_action,
            knockout_questions,
            qualification_questions,
            approved_ids
        )
    
    async def get_pre_screening(self, vacancy_id: uuid.UUID) -> Optional[dict]:
        """Get pre-screening configuration with questions."""
        ps_row = await self.repo.get_for_vacancy(vacancy_id)
        if not ps_row:
            return None
        
        questions = await self.repo.get_questions(ps_row["id"])
        
        return {
            "id": ps_row["id"],
            "vacancy_id": ps_row["vacancy_id"],
            "intro": ps_row["intro"],
            "knockout_failed_action": ps_row["knockout_failed_action"],
            "final_action": ps_row["final_action"],
            "status": ps_row["status"],
            "created_at": ps_row["created_at"],
            "updated_at": ps_row["updated_at"],
            "published_at": ps_row["published_at"],
            "is_online": ps_row["is_online"],
            "elevenlabs_agent_id": ps_row["elevenlabs_agent_id"],
            "whatsapp_agent_id": ps_row["whatsapp_agent_id"],
            "voice_enabled": ps_row["voice_enabled"],
            "whatsapp_enabled": ps_row["whatsapp_enabled"],
            "cv_enabled": ps_row["cv_enabled"],
            "questions": questions
        }
    
    async def delete_pre_screening(self, vacancy_id: uuid.UUID) -> bool:
        """
        Delete pre-screening configuration.
        
        Returns True if deleted, False if not found.
        """
        return await self.repo.delete(vacancy_id)
    
    async def publish_pre_screening(
        self,
        pre_screening_id: uuid.UUID,
        published_at: datetime,
        elevenlabs_agent_id: Optional[str],
        whatsapp_agent_id: Optional[str],
        voice_enabled: bool,
        whatsapp_enabled: bool,
        cv_enabled: bool
    ):
        """Publish pre-screening with agent IDs."""
        await self.repo.update_publish_state(
            pre_screening_id,
            published_at,
            elevenlabs_agent_id,
            whatsapp_agent_id,
            is_online=True,
            voice_enabled=voice_enabled,
            whatsapp_enabled=whatsapp_enabled,
            cv_enabled=cv_enabled
        )
    
    async def update_status(
        self,
        pre_screening_id: uuid.UUID,
        is_online: Optional[bool] = None,
        voice_enabled: Optional[bool] = None,
        whatsapp_enabled: Optional[bool] = None,
        cv_enabled: Optional[bool] = None
    ):
        """Update pre-screening status flags."""
        await self.repo.update_status_flags(
            pre_screening_id,
            is_online,
            voice_enabled,
            whatsapp_enabled,
            cv_enabled
        )
