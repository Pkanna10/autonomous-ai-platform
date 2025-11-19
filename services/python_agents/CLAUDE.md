# Python Agents Service - Claude Code Configuration

**Service:** `python_agents` **Primary Language:** Python 3.11+ **Framework:**
LangGraph 0.2.x **Testing:** pytest **Key Libraries:** langgraph, langchain,
anthropic

---

## 🎯 Service Purpose

Main LangGraph orchestrator service coordinating AI agents for intent parsing,
task planning, execution, and error recovery (Reflexion pattern).

---

## 🤖 LangGraph State Machine Patterns

### Basic Agent Structure

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated, Sequence
from langchain_core.messages import BaseMessage

class AgentState(TypedDict):
    """State shared across all agent nodes."""
    messages: Annotated[Sequence[BaseMessage], "conversation history"]
    user_input: str
    intent: str | None
    plan: dict | None
    result: dict | None
    error: str | None

def create_orchestrator() -> StateGraph:
    """Create main agent orchestrator graph."""
    graph = StateGraph(AgentState)

    # Add nodes
    graph.add_node("parse_intent", parse_intent_node)
    graph.add_node("plan_task", plan_task_node)
    graph.add_node("execute", execute_node)
    graph.add_node("reflect", reflect_on_error_node)

    # Add edges
    graph.add_edge("parse_intent", "plan_task")
    graph.add_edge("plan_task", "execute")

    # Conditional routing based on execution result
    graph.add_conditional_edges(
        "execute",
        should_retry,
        {
            "success": END,
            "retry": "reflect",
        }
    )

    graph.add_edge("reflect", "execute")

    # Set entry point
    graph.set_entry_point("parse_intent")

    return graph.compile()
```

### Node Implementation Pattern

```python
from langchain_anthropic import ChatAnthropic

async def parse_intent_node(state: AgentState) -> AgentState:
    """Parse user intent using Claude."""
    llm = ChatAnthropic(model="claude-sonnet-4-5-20250514")

    prompt = f"""
    Analyze this user request and identify the intent:
    "{state['user_input']}"

    Possible intents:
    - INSTALL_PACKAGE
    - SEARCH_RESEARCH
    - GENERATE_CODE
    - OPTIMIZE_CODE

    Return ONLY the intent name.
    """

    response = await llm.ainvoke([{"role": "user", "content": prompt}])
    intent = response.content.strip()

    return {
        **state,
        "intent": intent,
        "messages": state["messages"] + [response],
    }
```

### Reflexion Pattern (Error Recovery)

```python
def should_retry(state: AgentState) -> str:
    """Decide whether to retry after execution."""
    if state.get("error"):
        retry_count = state.get("retry_count", 0)
        if retry_count < 3:
            return "retry"
    return "success" if not state.get("error") else "failure"

async def reflect_on_error_node(state: AgentState) -> AgentState:
    """Reflect on error and generate fix strategy."""
    llm = ChatAnthropic(model="claude-sonnet-4-5-20250514")

    prompt = f"""
    Execution failed with error:
    {state['error']}

    Previous attempt:
    {state.get('plan', {})}

    Analyze the error and suggest a fix. What went wrong and how should we retry?
    """

    reflection = await llm.ainvoke([{"role": "user", "content": prompt}])

    return {
        **state,
        "plan": {"strategy": "retry", "reflection": reflection.content},
        "retry_count": state.get("retry_count", 0) + 1,
        "messages": state["messages"] + [reflection],
    }
```

---

## 🐍 Python Type Hints & Dataclasses

### Dataclass Patterns

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class Task:
    """Represents a user task."""
    id: str
    user_input: str
    intent: str
    status: str = "pending"  # pending, in_progress, success, failed
    created_at: datetime = field(default_factory=datetime.now)
    result: Optional[dict] = None
    error: Optional[str] = None

@dataclass
class ResearchQuery:
    """Research paper search query."""
    keywords: List[str]
    categories: List[str] = field(default_factory=lambda: ["cs.DS"])
    max_results: int = 10
    start_date: Optional[datetime] = None
```

### Advanced Type Hints

```python
from typing import Protocol, Callable, Awaitable, TypeVar

T = TypeVar('T')

class AgentNode(Protocol):
    """Protocol for agent node functions."""
    async def __call__(self, state: AgentState) -> AgentState:
        ...

# Async function type
AsyncNodeFunction = Callable[[AgentState], Awaitable[AgentState]]

# Generic repository pattern
class Repository(Protocol[T]):
    async def save(self, item: T) -> None:
        ...

    async def find_by_id(self, id: str) -> Optional[T]:
        ...
```

---

## 🧪 Pytest Patterns for Async Code

### Async Test Fixtures

```python
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

@pytest_asyncio.fixture
async def async_db_session():
    """Provide async database session for testing."""
    engine = create_async_engine('sqlite+aiosqlite:///:memory:')

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        yield session

    await engine.dispose()

@pytest.fixture
def mock_claude_client():
    """Provide mocked Claude client."""
    from unittest.mock import AsyncMock

    client = AsyncMock()
    client.ainvoke = AsyncMock(
        return_value={"content": "Mocked response"}
    )
    return client
```

### Testing Async Functions

```python
import pytest

@pytest.mark.asyncio
async def test_should_parse_intent_from_user_input(mock_claude_client):
    """
    GIVEN a user input requesting package installation
    WHEN parse_intent_node is called
    THEN should return INSTALL_PACKAGE intent
    """
    # GIVEN
    state = {
        "user_input": "install lodash for utility functions",
        "messages": [],
    }

    # WHEN
    result = await parse_intent_node(state)

    # THEN
    assert result["intent"] == "INSTALL_PACKAGE"
    assert len(result["messages"]) > 0
```

### Mocking LangGraph Execution

```python
from unittest.mock import patch, AsyncMock

@pytest.mark.asyncio
async def test_should_execute_full_agent_workflow():
    """Test complete agent execution from input to result."""
    # GIVEN
    graph = create_orchestrator()
    initial_state = {
        "user_input": "search for HyperLogLog papers",
        "messages": [],
    }

    with patch('services.python_agents.nodes.parse_intent_node') as mock_parse:
        mock_parse.return_value = {
            **initial_state,
            "intent": "SEARCH_RESEARCH"
        }

        # WHEN
        result = await graph.ainvoke(initial_state)

        # THEN
        assert result["intent"] == "SEARCH_RESEARCH"
        mock_parse.assert_called_once()
```

---

## 🔄 Agent Workflow Patterns

### Multi-Agent Collaboration

```python
from langgraph.graph import StateGraph

def create_multi_agent_system():
    """Create system with specialized agents."""
    graph = StateGraph(AgentState)

    # Specialized agents
    graph.add_node("research_agent", research_specialist_node)
    graph.add_node("code_agent", code_specialist_node)
    graph.add_node("test_agent", test_specialist_node)
    graph.add_node("router", route_to_specialist)

    # Router decides which specialist to use
    graph.add_conditional_edges(
        "router",
        lambda state: state["intent"],
        {
            "SEARCH_RESEARCH": "research_agent",
            "GENERATE_CODE": "code_agent",
            "WRITE_TESTS": "test_agent",
        }
    )

    graph.set_entry_point("router")

    return graph.compile()
```

### Human-in-the-Loop Pattern

```python
from langgraph.checkpoint.memory import MemorySaver

def create_interruptible_agent():
    """Create agent that can pause for human input."""
    memory = MemorySaver()
    graph = StateGraph(AgentState)

    graph.add_node("execute", execute_node)
    graph.add_node("ask_human", ask_for_approval)

    graph.add_conditional_edges(
        "execute",
        needs_approval,
        {
            "approve": "ask_human",
            "continue": END,
        }
    )

    # Compile with checkpointer for interruption
    return graph.compile(checkpointer=memory, interrupt_before=["ask_human"])

# Usage
app = create_interruptible_agent()
config = {"configurable": {"thread_id": "user-123"}}

# First execution - pauses at ask_human
result = await app.ainvoke(initial_state, config)

# Resume after human approval
result = await app.ainvoke({"approval": True}, config)
```

---

## 🔌 Anthropic SDK Integration

### Streaming Pattern

```python
from anthropic import AsyncAnthropic

async def stream_code_generation(prompt: str):
    """Stream code generation from Claude."""
    client = AsyncAnthropic()

    async with client.messages.stream(
        model="claude-sonnet-4-5-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        async for text in stream.text_stream:
            print(text, end="", flush=True)

        final_message = await stream.get_final_message()
        return final_message
```

### Tool Use Pattern

```python
tools = [
    {
        "name": "search_npm",
        "description": "Search NPM registry for packages",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    }
]

async def execute_with_tools(user_input: str):
    """Execute Claude request with tool calling."""
    client = AsyncAnthropic()

    response = await client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=1024,
        tools=tools,
        messages=[{"role": "user", "content": user_input}],
    )

    # Handle tool calls
    if response.stop_reason == "tool_use":
        tool_use = next(
            block for block in response.content if block.type == "tool_use"
        )

        # Execute tool
        tool_result = await execute_tool(tool_use.name, tool_use.input)

        # Continue conversation with tool result
        follow_up = await client.messages.create(
            model="claude-sonnet-4-5-20250514",
            max_tokens=1024,
            tools=tools,
            messages=[
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": response.content},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": str(tool_result),
                        }
                    ],
                },
            ],
        )

        return follow_up

    return response
```

---

## 📊 Monitoring & Logging

### Structured Logging

```python
import structlog
from datetime import datetime

logger = structlog.get_logger()

async def execute_node(state: AgentState) -> AgentState:
    """Execute node with structured logging."""
    logger.info(
        "node_execution_started",
        node="execute",
        user_input=state["user_input"],
        intent=state["intent"],
        timestamp=datetime.now().isoformat(),
    )

    try:
        result = await perform_execution(state)

        logger.info(
            "node_execution_success",
            node="execute",
            duration_ms=result.get("duration_ms"),
        )

        return result

    except Exception as e:
        logger.error(
            "node_execution_failed",
            node="execute",
            error=str(e),
            exc_info=True,
        )
        raise
```

---

## 📁 Key Files

| File                         | Purpose                     |
| ---------------------------- | --------------------------- |
| `orchestrator/main.py`       | Main LangGraph orchestrator |
| `orchestrator/nodes.py`      | Agent node implementations  |
| `orchestrator/state.py`      | AgentState definition       |
| `research/agent.py`          | Research specialist agent   |
| `tests/test_orchestrator.py` | Orchestrator tests          |
| `tests/test_nodes.py`        | Individual node tests       |
| `tests/conftest.py`          | Pytest fixtures             |

---

## ⚡ Performance Tips

### Parallel Node Execution

```python
# For independent nodes, execute in parallel
from langgraph.graph import StateGraph

graph.add_node("fetch_packages", fetch_packages_node)
graph.add_node("fetch_papers", fetch_papers_node)

# Both nodes execute in parallel
graph.add_edge("start", "fetch_packages")
graph.add_edge("start", "fetch_papers")

# Join results
graph.add_edge("fetch_packages", "combine_results")
graph.add_edge("fetch_papers", "combine_results")
```

---

**Last Updated:** 2025-11-19
