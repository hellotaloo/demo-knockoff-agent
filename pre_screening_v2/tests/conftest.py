"""
Shared pytest fixtures and configuration.
"""
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load env vars before any LiveKit imports
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

import pytest
import pytest_asyncio
from livekit.agents import AgentSession, inference

# Add project root to path so agent imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import CandidateData, SessionInput
from tests.configs import default_session_input
from tests.json_logger import TestRunLogger


# --- Session-scoped JSON logger ---

@pytest.fixture(scope="session")
def test_logger():
    """Session-wide test result logger. Writes JSON on teardown."""
    logger = TestRunLogger()
    yield logger
    filepath = logger.write()
    print(f"\nTest results written to {filepath}")


# --- LLM fixtures ---

@pytest_asyncio.fixture
async def llm():
    """LLM instance for the agent under test."""
    async with inference.LLM(model="openai/gpt-4.1-mini") as instance:
        yield instance


@pytest_asyncio.fixture
async def judge_llm():
    """Separate LLM instance for judging agent responses."""
    async with inference.LLM(model="openai/gpt-4.1-mini") as instance:
        yield instance


# --- Session factory ---

def make_session(llm_instance, inp: SessionInput | None = None) -> AgentSession:
    """Create an AgentSession with CandidateData userdata for testing."""
    if inp is None:
        inp = default_session_input()
    userdata = CandidateData(input=inp)
    userdata.room = None
    userdata.thinking_audio = None
    return AgentSession(llm=llm_instance, userdata=userdata)
