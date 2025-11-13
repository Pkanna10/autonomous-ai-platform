"""Agent state schema for LangGraph orchestrator.

Defines the shared state that flows through the agent graph.
"""

from typing import Annotated, TypedDict

from operator import add


class AgentState(TypedDict):
    """Central state schema for the agent graph.

    This state is passed between nodes and maintains the conversation
    and execution context.
    """

    # User input and intent
    user_input: str
    """Original user request."""

    intent: str | None
    """Detected intent type (e.g., 'INSTALL_PACKAGE', 'SEARCH_RESEARCH', 'GENERATE_CODE')."""

    # Execution context
    context: dict[str, str | int | float | bool | None]
    """Additional context for task execution."""

    # Message history (accumulated across nodes)
    messages: Annotated[list[str], add]
    """Message history for the conversation."""

    # Error tracking
    error: str | None
    """Error message if something went wrong."""

    # Results
    result: dict[str, str | int | float | bool | None] | None
    """Execution results to return to user."""
