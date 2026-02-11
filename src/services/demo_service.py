"""
Demo service - handles demo data seeding and reset.
"""
import asyncpg
from src.repositories import ConversationRepository


class DemoService:
    """Service for demo data operations."""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        self.conv_repo = ConversationRepository(pool)
    
    async def seed_demo_data(self, fixtures_data: dict) -> dict:
        """
        Seed database with demo data.
        
        Args:
            fixtures_data: Dictionary with vacancies, applications, pre_screenings
        
        Returns:
            Dictionary with counts of created records
        """
        # Implementation would call fixture loaders
        # This is a placeholder showing the structure
        return {
            "vacancies_created": 0,
            "applications_created": 0,
            "pre_screenings_created": 0
        }
    
    async def reset_demo_data(self) -> dict:
        """
        Reset demo data by clearing test records.
        
        Returns:
            Dictionary with counts of deleted records
        """
        # Delete all conversations (which includes test data)
        await self.conv_repo.delete_all()
        
        # Delete test applications
        result = await self.pool.execute(
            "DELETE FROM ats.applications WHERE is_test = true"
        )
        
        return {
            "conversations_deleted": "all",
            "test_applications_deleted": result
        }
