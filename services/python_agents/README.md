# Autonomous AI Agents - Python Services

LangGraph-based orchestrator and research agents for the autonomous AI platform.

## 📁 Project Structure

```
services/python_agents/
├── src/
│   └── autonomous_ai_agents/          # Main package (import name)
│       ├── orchestrator/               # LangGraph orchestrator (Phase 1, Week 3-4)
│       │   ├── __init__.py
│       │   ├── main.py                # Graph construction
│       │   ├── nodes.py               # Agent nodes
│       │   └── state.py               # AgentState definition
│       ├── research/                   # Research discovery (Phase 1, Week 7-8)
│       │   ├── __init__.py
│       │   ├── arxiv_monitor.py       # arXiv monitoring
│       │   └── pdf_parser.py          # PDF parsing
│       ├── common/                     # Shared utilities
│       │   ├── __init__.py
│       │   └── config.py              # Environment config
│       └── clients/                    # API clients
│           └── __init__.py
├── tests/                              # Test suite
│   ├── conftest.py                    # Shared fixtures
│   ├── orchestrator/
│   ├── research/
│   ├── common/
│   └── clients/
├── pyproject.toml                     # Package configuration
├── langgraph.json                     # LangGraph deployment config
├── .env.example                       # Environment template
└── README.md                          # This file
```

## 🚀 Quick Start

### Installation

```bash
# From services/python_agents/ directory

# 1. Create virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install package in editable mode with dev dependencies
python -m pip install -e ".[dev]"
```

### Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your actual credentials
nano .env  # or vim, code, etc.
```

### Usage

```python
from autonomous_ai_agents.orchestrator import Orchestrator

# Create orchestrator instance
orchestrator = Orchestrator()

# Execute a task
result = orchestrator.run("Install lodash package")
print(result)
```

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=autonomous_ai_agents --cov-report=html

# Run only unit tests (fast)
pytest -m unit

# Run specific test file
pytest tests/orchestrator/test_nodes.py

# Run in watch mode (requires pytest-watch)
ptw
```

## 🔍 Type Checking

```bash
# Run mypy type checker
mypy src/autonomous_ai_agents
```

## 🎨 Code Formatting

```bash
# Format with black
black src/ tests/

# Lint with ruff
ruff check src/ tests/

# Auto-fix ruff issues
ruff check --fix src/ tests/
```

## 📊 Development Status

### Phase 1: Foundation (Weeks 1-9) - IN PROGRESS

| Week | Component | Status |
|------|-----------|--------|
| 1-2 | Project setup, Docker, Database | ✅ Complete |
| 3-4 | **LangGraph orchestrator** | 🚧 Structure ready |
| 5-6 | Package Manager | ⏳ Upcoming |
| 7-8 | Research Engine | 📁 Placeholders created |
| 9 | State persistence | ⏳ Upcoming |

## 🏗️ Architecture

### LangGraph Orchestrator

The orchestrator uses LangGraph's state machine to coordinate tasks:

```
User Input → Intent Parser → Task Planner → Execution → Results
                                    ↓
                            Error Recovery (Reflexion)
```

### State Schema

```python
class AgentState(TypedDict):
    user_input: str                  # Original request
    intent: str | None               # Detected intent
    context: dict                    # Execution context
    messages: list[str]              # Message history
    error: str | None                # Error tracking
    result: dict | None              # Execution results
```

## 📚 Dependencies

### Core

- **langgraph** (>=0.2.0) - Agent orchestration framework
- **anthropic** (>=0.68.0) - Claude API client
- **pydantic** (>=2.0.0) - Data validation
- **pymupdf** (>=1.25.0) - PDF parsing
- **arxiv** (>=2.1.0) - arXiv API client

### Development

- **pytest** (>=8.0.0) - Testing framework
- **pytest-cov** - Coverage reporting
- **mypy** (>=1.13.0) - Type checking
- **ruff** (>=0.8.0) - Fast linting

## 🔗 Related Packages

- `packages/agent-core/` - TypeScript agent core
- `packages/research-engine/` - Research paper processing
- `packages/execution-engine/` - Code generation

## 📖 Documentation

- [CLAUDE.md](../../CLAUDE.md) - Complete project documentation
- [STATUS.md](../../STATUS.md) - Current sprint status
- [Implementation Timeline](../../CLAUDE.md#implementation-timeline) - 12-month roadmap

## 🤝 Contributing

This is a solo developer project. See [CLAUDE.md](../../CLAUDE.md) for:
- TDD workflow (Red-Green-Refactor)
- Code style guidelines
- Commit message format
- Testing requirements (90%+ coverage)

## 📄 License

MIT
