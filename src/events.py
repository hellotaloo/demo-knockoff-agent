"""
Domain Event Dispatcher.

Lightweight in-process event system for decoupling domain actions.
Producers emit events (e.g. "vacancy_archived"), consumers register
handlers that run independently.

Usage:
    # Register a handler (typically at module import time)
    @on("vacancy_archived")
    async def handle_vacancy_archived(pool, vacancy_id, **kwargs):
        ...

    # Emit an event (from any service)
    await emit("vacancy_archived", pool=pool, vacancy_id=vacancy_id)
"""
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

_handlers: dict[str, list[Callable]] = defaultdict(list)


def on(event: str):
    """Decorator to register an async handler for a domain event."""
    def decorator(func: Callable) -> Callable:
        _handlers[event].append(func)
        logger.debug(f"Registered handler {func.__module__}.{func.__name__} for event '{event}'")
        return func
    return decorator


async def emit(event: str, **kwargs):
    """Emit a domain event, calling all registered handlers."""
    handlers = _handlers.get(event, [])
    if not handlers:
        logger.debug(f"Event '{event}' emitted with no handlers")
        return

    for handler in handlers:
        try:
            await handler(**kwargs)
        except Exception:
            logger.exception(f"Handler {handler.__module__}.{handler.__name__} failed for event '{event}'")
