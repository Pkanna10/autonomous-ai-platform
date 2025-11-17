"""Shared pytest fixtures for all tests.

This file is automatically discovered by pytest and makes fixtures
available to all test files without explicit imports.
"""

import sys
from pathlib import Path
from typing import Any

import pytest

# Ensure src/ is on path (backup to pyproject.toml pythonpath config)
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def sample_agent_state() -> dict[str, Any]:
    """Provide a sample AgentState for testing.

    Returns:
        Dictionary matching AgentState schema
    """
    return {
        "user_input": "Install lodash package",
        "intent": "INSTALL_PACKAGE",
        "context": {},
        "messages": [],
        "error": None,
        "result": None,
    }


@pytest.fixture
def sample_user_inputs() -> list[str]:
    """Provide sample user inputs for intent parsing tests.

    Returns:
        List of diverse user request examples
    """
    return [
        "Install lodash package",
        "Search for papers on HyperLogLog algorithm",
        "Generate code for a React dashboard",
        "Optimize my sorting function",
        "What is the complexity of this algorithm?",
    ]


@pytest.fixture
def mock_claude_response() -> dict[str, Any]:
    """Provide a mock Claude API response.

    Returns:
        Mock response matching Anthropic API format
    """
    return {
        "id": "msg_test123",
        "content": [{"type": "text", "text": "Mocked Claude response"}],
        "model": "claude-sonnet-4-20250514",
        "role": "assistant",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


@pytest.fixture
def mock_anthropic_client(mocker: Any) -> Any:
    """Mock Anthropic client for testing without API calls.

    Args:
        mocker: pytest-mock fixture

    Returns:
        Mocked ClaudeClient instance
    """
    mock_client = mocker.patch(
        "autonomous_ai_agents.clients.claude_client.ClaudeClient"
    )
    mock_client.return_value.chat.return_value = {
        "content": [{"type": "text", "text": "Mocked response"}]
    }
    return mock_client


@pytest.fixture
def sample_arxiv_paper() -> dict[str, Any]:
    """Provide sample arXiv paper metadata.

    Returns:
        Dictionary with paper metadata
    """
    return {
        "id": "2301.12345",
        "title": "HyperLogLog: A Practical Algorithm for Streaming Aggregation",
        "authors": ["Author One", "Author Two"],
        "abstract": "This paper presents a novel approach to streaming aggregation...",
        "published": "2023-01-15",
        "categories": ["cs.DS", "cs.DB"],
    }


@pytest.fixture(autouse=True)
def reset_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset environment variables before each test.

    This auto-use fixture ensures tests don't leak environment state.

    Args:
        monkeypatch: pytest fixture for modifying environment
    """
    # Set test environment variables
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-12345")
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test_db")
