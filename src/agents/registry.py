"""
Agent Registry — central registry of all top-level Taloo agents.

Validates at startup that every registered agent has the required attributes
(agent_type, workflow_type) and lifecycle hooks. Provides lookup by AgentType.

Usage:
    @AgentRegistry.register
    class MyAgent(TalooAgent):
        agent_type = AgentType.MY_AGENT
        workflow_type = "my_workflow"
        ...

    # At startup
    AgentRegistry.validate_all()

    # At runtime
    agent_cls = AgentRegistry.get(AgentType.MY_AGENT)
    agent = agent_cls(pool=pool, workspace_id=workspace_id)
"""

import logging
from typing import Optional

from src.agents.base import AgentType, TalooAgent

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Central registry of all top-level Taloo agents."""

    _agents: dict[AgentType, type[TalooAgent]] = {}

    @classmethod
    def register(cls, agent_class: type[TalooAgent]) -> type[TalooAgent]:
        """Register a TalooAgent subclass. Used as a decorator.

        Validates that the class has the required class attributes
        (agent_type, workflow_type) before registration.

        Returns:
            The unmodified agent class (for use as @AgentRegistry.register).
        """
        # Validate required class attributes
        if not hasattr(agent_class, "agent_type") or agent_class.agent_type is None:
            raise TypeError(f"{agent_class.__name__} must define 'agent_type'")
        if not hasattr(agent_class, "workflow_type") or agent_class.workflow_type is None:
            raise TypeError(f"{agent_class.__name__} must define 'workflow_type'")

        agent_type = agent_class.agent_type
        if agent_type in cls._agents:
            raise ValueError(
                f"Agent type '{agent_type.value}' is already registered "
                f"by {cls._agents[agent_type].__name__}"
            )

        cls._agents[agent_type] = agent_class
        logger.info(f"Registered TalooAgent: {agent_class.__name__} (type={agent_type.value})")
        return agent_class

    @classmethod
    def get(cls, agent_type: AgentType) -> type[TalooAgent]:
        """Get a registered agent class by type.

        Raises:
            KeyError: If the agent type is not registered.
        """
        if agent_type not in cls._agents:
            raise KeyError(f"No agent registered for type '{agent_type.value}'")
        return cls._agents[agent_type]

    @classmethod
    def get_optional(cls, agent_type: AgentType) -> Optional[type[TalooAgent]]:
        """Get a registered agent class by type, or None if not registered."""
        return cls._agents.get(agent_type)

    @classmethod
    def all(cls) -> dict[AgentType, type[TalooAgent]]:
        """Return all registered agents."""
        return dict(cls._agents)

    @classmethod
    def validate_all(cls) -> None:
        """Validate all registered agents at startup.

        Checks that every AgentType enum value has a corresponding
        registered agent class. Logs warnings for missing registrations.
        """
        registered = set(cls._agents.keys())
        expected = set(AgentType)
        missing = expected - registered

        if missing:
            missing_names = ", ".join(t.value for t in missing)
            logger.warning(f"Unregistered agent types: {missing_names}")

        logger.info(
            f"Agent registry: {len(registered)}/{len(expected)} agent types registered"
        )
