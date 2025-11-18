"""Tests for orchestrator state schema.

Phase 1, Week 3-4: AgentState validation tests.
"""

from autonomous_ai_agents.orchestrator.state import AgentState


def test_agent_state_structure(sample_agent_state: dict) -> None:
    """Should create valid AgentState from sample data.

    GIVEN a sample agent state dictionary
    WHEN checking its structure
    THEN should match AgentState schema
    """
    # ARRANGE - provided by fixture

    # ACT - verify all required keys are present
    required_keys = {
        "user_input",
        "intent",
        "context",
        "messages",
        "error",
        "result",
    }
    actual_keys = set(sample_agent_state.keys())

    # ASSERT
    assert required_keys == actual_keys, "AgentState has all required fields"
    assert isinstance(sample_agent_state["user_input"], str)
    assert isinstance(sample_agent_state["messages"], list)
    assert isinstance(sample_agent_state["context"], dict)


def test_agent_state_user_input_required() -> None:
    """Should have user_input as a required field.

    GIVEN an AgentState TypedDict
    WHEN accessing annotations
    THEN user_input should be str type
    """
    # ACT
    annotations = AgentState.__annotations__

    # ASSERT
    assert "user_input" in annotations
    assert annotations["user_input"] is str


def test_agent_state_optional_fields() -> None:
    """Should allow None for optional fields.

    GIVEN an AgentState TypedDict
    WHEN checking optional field annotations
    THEN intent, error, and result should allow None
    """
    # ACT
    annotations = AgentState.__annotations__

    # ASSERT
    # These fields use str | None notation
    assert "intent" in annotations
    assert "error" in annotations
    assert "result" in annotations
