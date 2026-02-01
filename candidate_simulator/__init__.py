"""Candidate Simulator Agent - Simulates candidate responses for interview testing."""

from .agent import (
    build_simulator_instruction,
    create_simulator_agent,
    SimulationPersona,
    run_simulation,
)

__all__ = [
    "build_simulator_instruction",
    "create_simulator_agent", 
    "SimulationPersona",
    "run_simulation",
]
