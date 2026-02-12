"""
In-memory cache for conversation routing and agent instances.

Caches active conversation lookups to avoid repeated DB queries during
the same conversation. Also caches agent instances to avoid
deserializing/serializing agent state on every message.

Uses TTL to auto-expire stale entries.
"""
import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ConversationType(Enum):
    DOCUMENT_COLLECTION = "document_collection"
    PRE_SCREENING = "pre_screening"
    NONE = "none"


@dataclass
class CachedConversation:
    """Cached conversation routing info."""
    conversation_type: ConversationType
    conversation_id: Optional[str] = None
    vacancy_id: Optional[str] = None
    pre_screening_id: Optional[str] = None
    session_id: Optional[str] = None
    candidate_name: Optional[str] = None
    vacancy_title: Optional[str] = None
    cached_at: float = 0.0


@dataclass
class CachedAgent:
    """Cached agent instance with metadata."""
    agent: Any  # The actual agent object
    conversation_id: str
    cached_at: float = 0.0
    dirty: bool = False  # True if state needs to be saved to DB


class ConversationCache:
    """
    Simple TTL-based cache for conversation routing.

    Maps phone number -> active conversation info.
    TTL is short (60s) since conversations can change status.
    """

    def __init__(self, ttl_seconds: int = 60):
        self._cache: dict[str, CachedConversation] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    def _is_expired(self, entry: CachedConversation) -> bool:
        return time.time() - entry.cached_at > self._ttl

    async def get(self, phone: str) -> Optional[CachedConversation]:
        """Get cached conversation for phone number."""
        async with self._lock:
            entry = self._cache.get(phone)
            if entry and not self._is_expired(entry):
                logger.debug(f"Cache HIT for {phone}: {entry.conversation_type.value}")
                return entry
            elif entry:
                # Expired, remove it
                del self._cache[phone]
            return None

    async def set(
        self,
        phone: str,
        conversation_type: ConversationType,
        conversation_id: Optional[str] = None,
        vacancy_id: Optional[str] = None,
        pre_screening_id: Optional[str] = None,
        session_id: Optional[str] = None,
        candidate_name: Optional[str] = None,
        vacancy_title: Optional[str] = None,
    ):
        """Cache conversation routing info for phone number."""
        async with self._lock:
            self._cache[phone] = CachedConversation(
                conversation_type=conversation_type,
                conversation_id=conversation_id,
                vacancy_id=vacancy_id,
                pre_screening_id=pre_screening_id,
                session_id=session_id,
                candidate_name=candidate_name,
                vacancy_title=vacancy_title,
                cached_at=time.time(),
            )
            logger.debug(f"Cache SET for {phone}: {conversation_type.value}")

    async def invalidate(self, phone: str):
        """Remove cached entry for phone number."""
        async with self._lock:
            if phone in self._cache:
                del self._cache[phone]
                logger.debug(f"Cache INVALIDATED for {phone}")

    async def cleanup_expired(self):
        """Remove all expired entries."""
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._cache.items() if now - v.cached_at > self._ttl]
            for k in expired:
                del self._cache[k]
            if expired:
                logger.debug(f"Cache cleanup: removed {len(expired)} expired entries")

    async def clear_all(self):
        """Clear all cached entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Conversation cache CLEARED: removed {count} entries")
            return count


class AgentCache:
    """
    In-memory cache for agent instances.

    Caches agent objects to avoid loading/restoring from DB on every message.
    TTL is longer (5 min) since conversations are typically short-lived.
    """

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, CachedAgent] = {}
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()

    def _is_expired(self, entry: CachedAgent) -> bool:
        return time.time() - entry.cached_at > self._ttl

    async def get(self, conversation_id: str) -> Optional[Any]:
        """Get cached agent for conversation."""
        async with self._lock:
            entry = self._cache.get(conversation_id)
            if entry and not self._is_expired(entry):
                logger.debug(f"Agent cache HIT for {conversation_id[:8]}")
                return entry.agent
            elif entry:
                # Expired, remove it
                del self._cache[conversation_id]
                logger.debug(f"Agent cache EXPIRED for {conversation_id[:8]}")
            return None

    async def set(self, conversation_id: str, agent: Any):
        """Cache agent instance."""
        async with self._lock:
            self._cache[conversation_id] = CachedAgent(
                agent=agent,
                conversation_id=conversation_id,
                cached_at=time.time(),
                dirty=False,
            )
            logger.debug(f"Agent cache SET for {conversation_id[:8]}")

    async def invalidate(self, conversation_id: str):
        """Remove cached agent."""
        async with self._lock:
            if conversation_id in self._cache:
                del self._cache[conversation_id]
                logger.debug(f"Agent cache INVALIDATED for {conversation_id[:8]}")

    async def cleanup_expired(self):
        """Remove all expired entries."""
        async with self._lock:
            now = time.time()
            expired = [k for k, v in self._cache.items() if now - v.cached_at > self._ttl]
            for k in expired:
                del self._cache[k]
            if expired:
                logger.debug(f"Agent cache cleanup: removed {len(expired)} expired entries")

    async def clear_all(self):
        """Clear all cached agents."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Agent cache CLEARED: removed {count} entries")
            return count


# Global cache instances
conversation_cache = ConversationCache(ttl_seconds=60)
agent_cache = AgentCache(ttl_seconds=300)


async def clear_all_caches():
    """Clear all conversation and agent caches. Returns count of cleared entries."""
    conv_count = await conversation_cache.clear_all()
    agent_count = await agent_cache.clear_all()
    logger.info(f"All caches cleared: {conv_count} conversations, {agent_count} agents")
    return {"conversations": conv_count, "agents": agent_count}
