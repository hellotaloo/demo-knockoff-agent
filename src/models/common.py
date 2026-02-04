"""
Common models used across multiple endpoints.
"""
from typing import Generic, TypeVar, List
from pydantic import BaseModel, Field


T = TypeVar('T')


class PaginatedResponse(BaseModel, Generic[T]):
    """
    Generic paginated response model for list endpoints.

    This provides a consistent structure for all paginated list endpoints
    across the API.

    Example usage:
        @router.get("/items", response_model=PaginatedResponse[ItemResponse])
        async def list_items(limit: int = 50, offset: int = 0):
            items, total = await repo.list_items(limit=limit, offset=offset)
            return PaginatedResponse(
                items=items,
                total=total,
                limit=limit,
                offset=offset
            )
    """
    items: List[T] = Field(..., description="List of items in this page")
    total: int = Field(..., description="Total number of items across all pages", ge=0)
    limit: int = Field(..., description="Maximum number of items per page", ge=1)
    offset: int = Field(..., description="Number of items to skip", ge=0)

    class Config:
        json_schema_extra = {
            "example": {
                "items": [{"id": "123", "name": "Example"}],
                "total": 100,
                "limit": 50,
                "offset": 0
            }
        }
