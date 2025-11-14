# Python Dependency Management Research Report (2024-2025)

**Research Date:** November 14, 2025 **Project:** Autonomous AI Development
Platform **Focus:** pyproject.toml dependency strategies, lock files, and
security best practices

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Dependency Pinning Strategy](#dependency-pinning-strategy)
3. [Lock File Tool Comparison](#lock-file-tool-comparison)
4. [Version Constraint Operators](#version-constraint-operators)
5. [Monorepo Dependency Management](#monorepo-dependency-management)
6. [Optional Dependencies & Extras](#optional-dependencies--extras)
7. [Dev Dependencies Best Practices](#dev-dependencies-best-practices)
8. [Dependency Resolution Strategies](#dependency-resolution-strategies)
9. [Security Scanning Integration](#security-scanning-integration)
10. [PEP 751: Standard Lock File Format](#pep-751-standard-lock-file-format)
11. [Recommendations for This Project](#recommendations-for-this-project)
12. [Code Examples](#code-examples)
13. [References](#references)

---

## Executive Summary

### Key Findings

1. **Upper Bounds Are Harmful**: The Python community strongly discourages upper
   bounds on dependencies for libraries. They cause dependency conflicts and
   break the ecosystem.

2. **UV Is the Future**: UV (Rust-based) is 10-100x faster than pip and Poetry,
   with native monorepo support and excellent dependency resolution.

3. **Lock Files Are Essential**: For applications (not libraries), lock files
   ensure reproducible deployments. PEP 751 introduces a standard format, but
   tool adoption is ongoing.

4. **Libraries vs Applications**: Different strategies apply:
   - **Libraries**: Minimal constraints in pyproject.toml, no lock files
   - **Applications**: Flexible constraints in pyproject.toml, lock files for
     deployment

5. **Security First**: Integrate dependency scanning (Safety CLI, pip-audit)
   into CI/CD pipelines from day one.

### Quick Decision Matrix

| Scenario                | Tool          | Lock File   | Upper Bounds  | Security Scanning        |
| ----------------------- | ------------- | ----------- | ------------- | ------------------------ |
| **Library for PyPI**    | Poetry/UV     | ❌ No       | ❌ No         | ✅ Yes (CI only)         |
| **Application (prod)**  | UV/Poetry     | ✅ Yes      | ⚠️ Rare cases | ✅ Yes (CI + pre-commit) |
| **Monorepo (internal)** | UV            | ✅ Yes      | ❌ No         | ✅ Yes (CI)              |
| **Research scripts**    | pip/pip-tools | ⚠️ Optional | ⚠️ Optional   | ⚠️ Optional              |

---

## Dependency Pinning Strategy

### The Upper Bounds Debate

#### Community Consensus (2024-2025)

**Avoid Upper Bounds on Library Dependencies**

The Python packaging community strongly discourages placing upper bounds on
dependency versions for libraries. Key reasons:

1. **Dependency Hell**: Upper bounds create conflicts when multiple libraries
   constrain the same dependency to incompatible ranges.

   ```
   Example Conflict:
   library-a: requests >= 2.25, < 3.0
   library-b: requests >= 2.28, < 4.0
   library-c: requests >= 3.0, < 4.0

   Result: No version of requests satisfies all three constraints
   ```

2. **False Assumptions**: You don't know future versions are incompatible unless
   you've tested them. Upper bounds assume breakage before it occurs.

3. **Ecosystem Fragmentation**: Projects with upper bounds prevent users from
   adopting newer, secure versions of dependencies.

4. **Official Guidance**: The
   [Python Packaging User Guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
   explicitly warns against upper bounds.

#### When Upper Bounds Are Acceptable

**Rare exceptions where upper bounds make sense:**

1. **Known Breaking Changes**: When a dependency explicitly announces breaking
   changes in a future major version.

   ```toml
   # Example: Django 5.0 dropped Python 3.8/3.9 support
   dependencies = [
       "django >= 4.2, < 5.0; python_version < '3.10'",
       "django >= 5.0; python_version >= '3.10'"
   ]
   ```

2. **Security Vulnerabilities**: Temporarily blocking vulnerable versions until
   patches are released.

   ```toml
   dependencies = [
       "requests >= 2.31.0, != 2.31.1"  # CVE-2023-XXXXX in 2.31.1
   ]
   ```

3. **Alpha/Beta Dependencies**: When depending on unstable pre-release software.

   ```toml
   dependencies = [
       "experimental-lib >= 0.1.0a1, < 0.2.0"
   ]
   ```

### Recommended Pinning Strategies

#### Strategy 1: Libraries (Minimal Constraints)

**For packages published to PyPI:**

```toml
[project]
name = "my-library"
version = "1.0.0"
dependencies = [
    "requests >= 2.28.0",           # No upper bound
    "numpy >= 1.24.0",               # No upper bound
    "pydantic >= 2.0.0",             # No upper bound (major version jump acceptable)
]
```

**Rationale:**

- Trust semantic versioning
- Allow users to get security updates
- Prevent dependency conflicts in downstream projects

#### Strategy 2: Applications (Flexible Constraints + Lock Files)

**For deployable applications:**

```toml
[project]
name = "my-application"
version = "1.0.0"
dependencies = [
    "fastapi >= 0.100.0",           # Flexible lower bound
    "sqlalchemy >= 2.0.0",          # Major version specified
    "redis >= 4.5.0",               # No upper bound
]
```

**Plus a lock file (uv.lock or poetry.lock):**

- Lock file pins exact versions for reproducible builds
- pyproject.toml allows version flexibility
- Best of both worlds: flexibility + reproducibility

#### Strategy 3: Monorepo (Path Dependencies)

**For internal monorepo packages:**

```toml
[project]
name = "research-engine"
dependencies = [
    "agent-core",  # Internal package (version handled by monorepo tool)
    "anthropic >= 0.40.0",
    "langgraph >= 0.2.0",
]

[tool.uv.sources]
agent-core = { path = "../agent-core", editable = true }
```

**Rationale:**

- Internal packages don't need version constraints
- Editable installs for rapid development
- Lock file ensures external dependencies are reproducible

---

## Lock File Tool Comparison

### Overview

| Feature                  | **UV**                         | **Poetry**                       | **pip-tools**                     |
| ------------------------ | ------------------------------ | -------------------------------- | --------------------------------- |
| **Speed**                | ⚡⚡⚡ 10-100x faster          | ⚡ Moderate                      | ⚡⚡ Fast                         |
| **Lock File**            | uv.lock                        | poetry.lock                      | requirements.txt                  |
| **Written In**           | Rust 🦀                        | Python 🐍                        | Python 🐍                         |
| **Monorepo Support**     | ✅ Native workspace support    | ⚠️ Limited (plugins)             | ❌ Manual per-package             |
| **Python Version Mgmt**  | ✅ Built-in (uv python)        | ❌ Requires pyenv/asdf           | ❌ Requires pyenv/asdf            |
| **PEP 621 Support**      | ✅ Full support                | ✅ Poetry 2.0+                   | ✅ Via pip                        |
| **Maturity**             | 🆕 1.5 years (2023-2025)       | 🏆 7+ years                      | 🏆 8+ years                       |
| **Deterministic Builds** | ✅ Yes (cross-platform)        | ✅ Yes                           | ✅ Yes (with --generate-hashes)   |
| **Hashes**               | ✅ Included                    | ✅ Included                      | ⚠️ Optional (--generate-hashes)   |
| **Offline Support**      | ✅ Aggressive caching          | ⚠️ Limited                       | ❌ No                             |
| **Dependency Groups**    | ✅ PEP 735                     | ⚠️ Via extras                    | ❌ Multiple .in files             |
| **Best For**             | New projects, monorepos, CI/CD | Mature projects, PyPI publishing | Simple projects, legacy codebases |

### Detailed Comparison

#### UV (Recommended for This Project)

**Pros:**

- **Blazing Fast**: Rust-based, 10-100x faster than pip/Poetry
- **Monorepo Native**: Workspace support with `uv workspace`
- **Python Version Management**: No need for pyenv (`uv python install 3.11`)
- **Modern Standards**: Full PEP 621 support
- **Deterministic**: Cross-platform reproducible builds
- **Aggressive Caching**: Offline installs from cache
- **Zero Dependencies**: Single binary, no bootstrapping required

**Cons:**

- **Young**: Only 1.5 years old (less mature than Poetry)
- **Ecosystem Adoption**: Not yet universally supported
- **Documentation**: Still growing compared to Poetry

**Lock File Format (uv.lock):**

```toml
version = 1
requires-python = ">=3.11"

[[package]]
name = "anthropic"
version = "0.40.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "httpx" },
]
wheels = [
    { url = "https://files.pythonhosted.org/...", hash = "sha256:..." },
]
```

**When to Use UV:**

- ✅ New projects (greenfield)
- ✅ Monorepo architectures
- ✅ CI/CD pipelines (speed matters)
- ✅ Teams wanting modern tooling

#### Poetry (Battle-Tested Alternative)

**Pros:**

- **Mature**: 7+ years of production use
- **Feature-Complete**: Publishing, packaging, dependency management in one tool
- **Large Ecosystem**: Plugins, integrations, community support
- **Excellent Documentation**: Comprehensive guides and examples
- **PyPI Publishing**: Built-in `poetry publish` command

**Cons:**

- **Slower**: Python-based dependency resolver can be slow (minutes for complex
  graphs)
- **Monorepo Support**: Limited (requires poetry-monorepo plugin)
- **Complexity**: More moving parts than UV

**Lock File Format (poetry.lock):**

```toml
[[package]]
name = "anthropic"
version = "0.40.0"
description = "..."
category = "main"
optional = false
python-versions = ">=3.8"

[package.dependencies]
httpx = ">=0.24.0,<1.0.0"

[metadata.files]
anthropic = [
    {file = "anthropic-0.40.0-py3-none-any.whl", hash = "sha256:..."},
]
```

**When to Use Poetry:**

- ✅ Existing Poetry projects (migration cost)
- ✅ Publishing libraries to PyPI
- ✅ Teams familiar with Poetry workflow
- ✅ Need stable, proven tooling

#### pip-tools (Minimalist Option)

**Pros:**

- **Simple**: Minimal learning curve (uses standard pip)
- **Lightweight**: No heavy dependencies
- **Legacy-Friendly**: Works with any pip-compatible project

**Cons:**

- **Manual Workflow**: Requires explicit pip-compile step
- **No Monorepo Support**: Each package needs separate requirements.txt
- **No Python Version Management**: Requires external tools
- **Basic Hashing**: Optional (--generate-hashes flag)

**Lock File Format (requirements.txt):**

```
# This file is autogenerated by pip-compile with Python 3.11
anthropic==0.40.0 \
    --hash=sha256:...
httpx==0.27.0 \
    --hash=sha256:...
```

**When to Use pip-tools:**

- ✅ Simple projects with few dependencies
- ✅ Legacy codebases already using requirements.txt
- ✅ Teams wanting minimal tooling overhead

### Lock File Best Practices

#### 1. Always Commit Lock Files for Applications

```bash
# Your repository should include:
✅ pyproject.toml     # Flexible dependencies
✅ uv.lock            # Exact versions for reproducibility
✅ .python-version    # Python version pinning
```

**Rationale:**

- Ensures all developers use identical dependency versions
- Prevents "works on my machine" issues
- Enables fast CI/CD (no dependency resolution during builds)

#### 2. Never Commit Lock Files for Libraries

```bash
# For PyPI libraries:
✅ pyproject.toml     # Flexible dependencies (no upper bounds)
❌ poetry.lock        # Do NOT commit (confuses users)
❌ uv.lock            # Do NOT commit (not relevant to library users)
```

**Rationale:**

- Library users have their own lock files
- Committed lock files can mislead users about supported versions
- Libraries should work with a range of dependency versions

#### 3. Regenerate Lock Files Regularly

```bash
# Weekly or monthly (depending on project velocity)
uv lock --upgrade            # UV
poetry update                # Poetry
pip-compile --upgrade        # pip-tools
```

**Rationale:**

- Get security patches
- Test against newer dependency versions
- Avoid sudden breakage from large version jumps

#### 4. Lock File CI Checks

**Add to .github/workflows/ci.yml:**

```yaml
- name: Check lock file is up-to-date
  run: |
    uv lock --check           # UV
    # OR
    poetry check --lock       # Poetry
```

**Rationale:**

- Prevents stale lock files
- Catches when someone updates pyproject.toml but forgets to regenerate lock

---

## Version Constraint Operators

### Operator Reference

| Operator | Name               | Example              | Meaning                  | Use Case                                 |
| -------- | ------------------ | -------------------- | ------------------------ | ---------------------------------------- |
| `==`     | Exact              | `requests == 2.31.0` | Pin to exact version     | Lock files, known working versions       |
| `>=`     | Greater or Equal   | `requests >= 2.28.0` | Minimum version          | **Recommended for libraries**            |
| `<=`     | Less or Equal      | `requests <= 3.0.0`  | Maximum version          | ⚠️ Discouraged (see upper bounds debate) |
| `~=`     | Compatible Release | `requests ~= 2.31.0` | >= 2.31.0, < 2.32.0      | Conservative updates (patch only)        |
| `^`      | Caret (Poetry)     | `requests ^2.31.0`   | >= 2.31.0, < 3.0.0       | SemVer-compatible updates                |
| `!=`     | Exclusion          | `requests != 2.31.1` | Exclude specific version | Blocking broken/vulnerable versions      |

### Operator Deep Dive

#### `>=` (Greater or Equal) - **RECOMMENDED FOR LIBRARIES**

**Meaning:** Require at least this version, no upper limit.

```toml
dependencies = [
    "requests >= 2.28.0",
    "numpy >= 1.24.0",
]
```

**When to use:**

- ✅ Libraries published to PyPI
- ✅ When you trust semantic versioning
- ✅ To allow users to get security updates

**Why recommended:**

- Prevents dependency conflicts
- Allows ecosystem to move forward
- Follows Python packaging best practices

#### `~=` (Compatible Release) - PEP 440 Standard

**Meaning:** Allows updates that are expected to be compatible (patch-level
changes).

```toml
dependencies = [
    "requests ~= 2.31.0",  # Equivalent to >= 2.31.0, < 2.32.0
    "django ~= 4.2",       # Equivalent to >= 4.2, < 5.0
]
```

**Rules:**

- `~= X.Y.Z` → `>= X.Y.Z, < X.Y+1.0`
- `~= X.Y` → `>= X.Y, < X+1.0`

**When to use:**

- ⚠️ Applications where you want conservative updates
- ⚠️ Dependencies with unstable APIs

**Why NOT recommended for libraries:**

- Creates upper bounds (discouraged by community)
- Can cause dependency conflicts

#### `^` (Caret) - Poetry-Specific (NOT PEP 440)

**Meaning:** Allows SemVer-compatible updates (won't break API).

```toml
# Poetry only
[tool.poetry.dependencies]
requests = "^2.31.0"  # Equivalent to >= 2.31.0, < 3.0.0
numpy = "^1.24.0"     # Equivalent to >= 1.24.0, < 2.0.0
```

**Rules (SemVer-based):**

- `^1.2.3` → `>= 1.2.3, < 2.0.0`
- `^0.2.3` → `>= 0.2.3, < 0.3.0` (0.x is special-cased)

**When to use:**

- ⚠️ Poetry projects (not portable to standard pyproject.toml)
- ⚠️ Dependencies that follow semantic versioning

**Why NOT recommended:**

- Not standard Python (Poetry-specific syntax)
- Creates upper bounds (discouraged)
- Use `>=` instead for portability

#### `!=` (Exclusion) - For Broken Versions

**Meaning:** Exclude specific versions (e.g., known bugs, vulnerabilities).

```toml
dependencies = [
    "requests >= 2.28.0, != 2.31.1",  # CVE-XXXX-YYYY in 2.31.1
    "django >= 4.2, != 4.2.0",        # 4.2.0 had critical bug
]
```

**When to use:**

- ✅ Blocking known broken versions
- ✅ Excluding versions with security vulnerabilities
- ✅ Temporary workaround until upstream fixes are released

**Example from real world:**

```toml
# Certifi 2022.12.07 had expired root certificate
dependencies = [
    "certifi >= 2022.6.15, != 2022.12.07"
]
```

### Recommended Patterns

#### Pattern 1: Library Dependencies (Minimal Constraints)

```toml
[project]
dependencies = [
    "anthropic >= 0.40.0",           # No upper bound
    "langgraph >= 0.2.0",            # No upper bound
    "pydantic >= 2.0.0",             # Major version OK
]
```

#### Pattern 2: Application Dependencies (Flexible + Lock File)

```toml
[project]
dependencies = [
    "fastapi >= 0.100.0",            # Flexible
    "sqlalchemy >= 2.0.0",           # Flexible
]
```

**Plus uv.lock with exact versions:**

```
fastapi==0.109.0
sqlalchemy==2.0.27
```

#### Pattern 3: Excluding Broken Versions

```toml
[project]
dependencies = [
    "requests >= 2.28.0, != 2.31.1",  # Skip vulnerable version
    "urllib3 >= 2.0.0, != 2.0.3",     # Skip broken release
]
```

#### Pattern 4: Python Version Constraints

```toml
[project]
requires-python = ">=3.11"  # No upper bound on Python version

dependencies = [
    # Conditional dependencies based on Python version
    "typing-extensions >= 4.5.0; python_version < '3.12'",
]
```

---

## Monorepo Dependency Management

### Monorepo Structure for Python Projects

**Recommended structure:**

```
autonomous-ai-platform/
├── pyproject.toml              # Root workspace config
├── uv.lock                     # Shared lock file
├── .python-version             # Python 3.11
├── packages/
│   ├── agent-core/
│   │   ├── pyproject.toml      # Package metadata
│   │   └── src/agent_core/
│   ├── research-engine/
│   │   ├── pyproject.toml
│   │   └── src/research_engine/
│   └── execution-engine/
│       ├── pyproject.toml
│       └── src/execution_engine/
└── services/
    └── python_agents/
        ├── pyproject.toml
        └── src/python_agents/
```

### UV Workspace Configuration

**Root pyproject.toml:**

```toml
[project]
name = "autonomous-ai-platform"
version = "0.1.0"
requires-python = ">=3.11"

# Define workspace members
[tool.uv.workspace]
members = [
    "packages/agent-core",
    "packages/research-engine",
    "packages/execution-engine",
    "services/python_agents",
]

# Shared dev dependencies (optional)
[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",
    "ruff >= 0.6.0",
    "mypy >= 1.10.0",
]
```

**Package pyproject.toml (packages/research-engine/pyproject.toml):**

```toml
[project]
name = "research-engine"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "agent-core",              # Internal workspace dependency
    "anthropic >= 0.40.0",     # External dependency
    "pymupdf >= 1.24.0",       # External dependency
]

# Specify internal package sources
[tool.uv.sources]
agent-core = { workspace = true }  # Points to packages/agent-core

[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",
]
```

**Installing workspace:**

```bash
# Install all packages in workspace
uv sync

# Install specific package with dev dependencies
uv sync --package research-engine --extra dev

# Install in editable mode for development
uv pip install -e packages/research-engine
```

### Poetry Monorepo (Alternative)

**Requires plugin:** `poetry-monorepo` or manual path dependencies

**Root pyproject.toml:**

```toml
[tool.poetry]
name = "autonomous-ai-platform"
version = "0.1.0"

# Not officially supported - workaround needed
```

**Package pyproject.toml:**

```toml
[tool.poetry]
name = "research-engine"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.11"
agent-core = { path = "../agent-core", develop = true }
anthropic = "^0.40.0"
```

**Limitations:**

- No official workspace support (requires plugins)
- Each package needs separate poetry.lock
- More complex setup than UV

### Monorepo Best Practices

#### 1. Single Lock File at Root

```bash
# UV automatically manages single lock file
✅ uv.lock                    # Root-level, shared across packages
❌ packages/agent-core/uv.lock  # Don't create per-package locks
```

**Benefits:**

- All packages use same dependency versions
- Faster CI (single dependency resolution)
- Easier to reason about

#### 2. Use Workspace Protocol

```toml
# In package pyproject.toml
dependencies = [
    "agent-core",  # Automatically resolved to workspace package
]

[tool.uv.sources]
agent-core = { workspace = true }
```

**Benefits:**

- No manual path management
- Automatic version resolution
- Works across packages

#### 3. Shared vs Package-Specific Dependencies

**Shared (root pyproject.toml):**

```toml
[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",     # All packages use same testing framework
    "ruff >= 0.6.0",       # Shared linting
    "mypy >= 1.10.0",      # Shared type checking
]
```

**Package-specific (package pyproject.toml):**

```toml
[project]
dependencies = [
    "pymupdf >= 1.24.0",   # Only research-engine needs PDF parsing
    "arxiv >= 2.1.0",      # Only research-engine needs arXiv API
]
```

#### 4. Development Workflow

```bash
# Install entire workspace
uv sync

# Install specific package
uv sync --package research-engine

# Add dependency to specific package
cd packages/research-engine
uv add anthropic

# Run tests for specific package
cd packages/research-engine
pytest tests/

# Run tests for all packages
pytest packages/*/tests/
```

---

## Optional Dependencies & Extras

### Understanding Extras

**Extras** are optional feature sets that users can selectively install.

**Syntax:**

```bash
pip install mypackage[feature1,feature2]
```

### Defining Extras in pyproject.toml

```toml
[project]
name = "research-engine"
dependencies = [
    "anthropic >= 0.40.0",  # Always installed
]

[project.optional-dependencies]
# Extra for arXiv integration
arxiv = [
    "arxiv >= 2.1.0",
    "pymupdf >= 1.24.0",
]

# Extra for ACM integration
acm = [
    "beautifulsoup4 >= 4.12.0",
    "lxml >= 5.0.0",
]

# Extra for all research sources
all-sources = [
    "research-engine[arxiv,acm]",  # Recursive extras (pip 21.2+)
]

# Dev dependencies
dev = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "ruff >= 0.6.0",
]

# Testing dependencies
test = [
    "pytest >= 8.0.0",
    "pytest-mock >= 3.12.0",
]

# Documentation dependencies
docs = [
    "sphinx >= 7.0.0",
    "sphinx-rtd-theme >= 2.0.0",
]

# All dev tools
dev-all = [
    "research-engine[dev,test,docs]",
]
```

### Installation Patterns

```bash
# Install base package only
uv pip install research-engine

# Install with arXiv support
uv pip install research-engine[arxiv]

# Install with multiple extras
uv pip install research-engine[arxiv,acm]

# Install with all extras
uv pip install research-engine[all-sources]

# Install for development
uv pip install -e .[dev]

# Install with all dev tools
uv pip install -e .[dev-all]
```

### Extras Organization Patterns

#### Pattern 1: Feature-Based Extras

**For packages with optional features:**

```toml
[project.optional-dependencies]
# Database backends
postgres = ["psycopg[binary] >= 3.1.0"]
mysql = ["pymysql >= 1.1.0"]
sqlite = ["aiosqlite >= 0.19.0"]

# Cache backends
redis = ["redis >= 5.0.0"]
memcached = ["pymemcache >= 4.0.0"]

# All backends
all-backends = [
    "mypackage[postgres,mysql,sqlite,redis,memcached]",
]
```

#### Pattern 2: Environment-Based Extras

**For different deployment environments:**

```toml
[project.optional-dependencies]
# Development tools
dev = [
    "pytest >= 8.0.0",
    "pytest-watch >= 4.2.0",
    "ipdb >= 0.13.0",
]

# Production monitoring
prod = [
    "prometheus-client >= 0.19.0",
    "sentry-sdk >= 2.0.0",
]

# Testing
test = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
]
```

#### Pattern 3: Role-Based Extras

**For different user types:**

```toml
[project.optional-dependencies]
# For library users
cli = [
    "click >= 8.1.0",
    "rich >= 13.7.0",
]

# For API users
api = [
    "fastapi >= 0.100.0",
    "uvicorn >= 0.27.0",
]

# For contributors
dev = [
    "pytest >= 8.0.0",
    "ruff >= 0.6.0",
    "pre-commit >= 3.6.0",
]
```

### Dependency Groups vs Extras

**PEP 735: Dependency Groups (Coming Soon)**

Dependency groups are metadata for organizing dependencies by development
context, while extras are part of published package metadata.

**Key Differences:**

| Feature         | Extras                       | Dependency Groups        |
| --------------- | ---------------------------- | ------------------------ |
| **Purpose**     | Optional features for users  | Dev tool organization    |
| **Published**   | ✅ Yes (in package metadata) | ❌ No (development only) |
| **User-Facing** | ✅ Yes                       | ❌ No                    |
| **Standard**    | PEP 621                      | PEP 735 (draft)          |

**Example (future PEP 735 syntax):**

```toml
[dependency-groups]
test = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
]

lint = [
    "ruff >= 0.6.0",
    "mypy >= 1.10.0",
]

docs = [
    "sphinx >= 7.0.0",
]
```

**For now, use extras for dev dependencies:**

```toml
[project.optional-dependencies]
dev = ["pytest", "ruff", "mypy"]
```

---

## Dev Dependencies Best Practices

### The State of Dev Dependencies in 2024

**Important Context:** There is **no standardized way** to specify dev
dependencies in pyproject.toml (as of PEP 621). Each tool has its own approach.

### Recommended Approach: Use Extras

**Standard-compliant method (works with all tools):**

```toml
[project]
name = "my-package"
dependencies = [
    "requests >= 2.28.0",  # Production dependencies
]

[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",
    "ruff >= 0.6.0",
    "mypy >= 1.10.0",
    "pre-commit >= 3.6.0",
]
```

**Installation:**

```bash
# Install package in editable mode with dev dependencies
pip install -e .[dev]

# Or with UV
uv pip install -e .[dev]
```

### Tool-Specific Approaches

#### UV (Recommended)

**Uses standard extras:**

```toml
[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",
    "ruff >= 0.6.0",
]
```

**Installing:**

```bash
uv sync --extra dev
```

#### Poetry

**Uses tool-specific section:**

```toml
[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.28.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
ruff = "^0.6.0"
mypy = "^1.10.0"
```

**Installing:**

```bash
poetry install --with dev
```

**Note:** Poetry 2.0+ also supports standard `[project.optional-dependencies]`.

### Dev Dependency Organization

#### Pattern 1: Single "dev" Extra (Simple Projects)

```toml
[project.optional-dependencies]
dev = [
    # Testing
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",

    # Linting
    "ruff >= 0.6.0",

    # Type checking
    "mypy >= 1.10.0",

    # Git hooks
    "pre-commit >= 3.6.0",
]
```

**When to use:**

- ✅ Small projects
- ✅ Solo developers
- ✅ Simple development workflows

#### Pattern 2: Multiple Extras (Complex Projects)

```toml
[project.optional-dependencies]
# Testing dependencies
test = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
    "pytest-mock >= 3.12.0",
]

# Linting dependencies
lint = [
    "ruff >= 0.6.0",
    "black >= 24.0.0",
    "isort >= 5.13.0",
]

# Type checking dependencies
type-check = [
    "mypy >= 1.10.0",
    "types-requests >= 2.31.0",
]

# Documentation dependencies
docs = [
    "sphinx >= 7.0.0",
    "sphinx-rtd-theme >= 2.0.0",
]

# All dev dependencies
dev = [
    "my-package[test,lint,type-check,docs]",
    "pre-commit >= 3.6.0",
]
```

**When to use:**

- ✅ Large projects
- ✅ CI/CD workflows (install only what's needed)
- ✅ Teams with specialized roles

**CI usage:**

```yaml
# .github/workflows/ci.yml
- name: Install test dependencies
  run: uv pip install -e .[test]

- name: Install lint dependencies
  run: uv pip install -e .[lint]
```

#### Pattern 3: Recursive Extras

**Using pip 21.2+ recursive extras feature:**

```toml
[project.optional-dependencies]
test = [
    "pytest >= 8.0.0",
]

lint = [
    "ruff >= 0.6.0",
]

# Combine multiple extras
dev = [
    "my-package[test,lint]",  # Recursive dependency
    "ipdb >= 0.13.0",         # Add debugging tool
]
```

---

## Dependency Resolution Strategies

### How Dependency Resolution Works

**Dependency resolution** is the process of finding a set of package versions
that satisfy all constraints.

**The Problem:** This is an **NP-hard problem** (like sudoku), meaning
worst-case resolution time grows exponentially with complexity.

### Resolution Algorithms

#### pip (20.3+)

**Algorithm:** Backtracking with conflict resolution

**How it works:**

1. Collect all requirements
2. Build dependency graph
3. Attempt to find compatible versions
4. If conflict found, backtrack and try different version
5. Repeat until solution found or exhausted

**Performance:**

- Moderate speed for simple graphs
- Can be very slow for complex graphs (minutes to hours)
- Improved in pip 24.2 (July 2024) with better caching

**Optimizations (pip 24.2):**

- Requirements caching (parse once, reuse many times)
- 256KB chunk downloads (was 10KB)
- Faster package discovery on Python 3.11+

#### Poetry

**Algorithm:** Depth-first search (DFS) with SAT solver

**How it works:**

- Python-based resolver
- Explores dependency tree depth-first
- Uses constraint satisfaction

**Performance:**

- Can be slow for complex graphs
- Benefits from caching after first resolution

**Known Issues:**

- Slow on large dependency graphs
- No parallelization (single-threaded Python)

#### UV

**Algorithm:** Advanced SAT solver with algebraic decision diagrams

**How it works:**

- Rust-based implementation
- Parallel downloads
- Simplifies dependency markers using algebraic decision diagrams
- Efficient caching and reuse

**Performance:**

- **10-100x faster** than pip/Poetry
- Sub-second resolution for most projects
- Handles complex graphs efficiently

**Why so fast:**

- Rust (native code, no GIL)
- Parallel operations
- Advanced algorithms
- Aggressive caching

### Conflict Resolution Strategies

#### Strategy 1: Preventive - Minimize Constraints

**Avoid the problem by using flexible constraints:**

```toml
# ✅ Good: Flexible constraints
dependencies = [
    "requests >= 2.28.0",
    "numpy >= 1.24.0",
]

# ❌ Bad: Overly strict constraints
dependencies = [
    "requests >= 2.28.0, < 3.0.0",
    "numpy >= 1.24.0, < 2.0.0",
]
```

#### Strategy 2: Detection - Use pip check

**Check for conflicts after installation:**

```bash
# Check for incompatibilities
pip check

# Example output:
# requests 2.31.0 requires urllib3<3,>=1.21.1, but you have urllib3 3.0.0
```

**Tools:**

- `pip check` - Built-in
- `pipdeptree` - Visualize dependency tree
- `pip-conflict-checker` - Detailed conflict analysis

#### Strategy 3: Resolution - Adjust Versions

**Manual version adjustments:**

```bash
# 1. Identify conflict
pip check

# 2. Adjust version constraints
# Edit pyproject.toml to relax constraints

# 3. Regenerate lock file
uv lock --upgrade

# 4. Verify resolution
pip check
```

#### Strategy 4: Isolation - Use Virtual Environments

**Prevent conflicts between projects:**

```bash
# Create isolated environment
uv venv .venv

# Activate
source .venv/bin/activate

# Install dependencies
uv sync
```

#### Strategy 5: Override - Constraint Files

**Force specific versions:**

```bash
# constraints.txt
urllib3==2.2.0
certifi==2024.2.2

# Install with constraints
pip install -c constraints.txt -r requirements.txt
```

### Common Conflict Scenarios

#### Scenario 1: Diamond Dependency Conflict

```
Your Project
├── package-a >= 2.0
│   └── shared-lib >= 1.5, < 2.0
└── package-b >= 3.0
    └── shared-lib >= 2.0, < 3.0

ERROR: No version of shared-lib satisfies both constraints
```

**Solutions:**

1. Update package-a or package-b to compatible versions
2. Contact maintainers to relax constraints
3. Use older versions of package-a or package-b

#### Scenario 2: Python Version Incompatibility

```
Your Project (Python 3.11)
└── old-package >= 1.0
    └── requires: Python < 3.10

ERROR: old-package is not compatible with Python 3.11
```

**Solutions:**

1. Update to newer version of old-package
2. Downgrade Python version (not recommended)
3. Find alternative package

#### Scenario 3: Transitive Dependency Hell

```
Your Project
├── django >= 4.2
│   └── sqlparse >= 0.4.2
└── mypackage >= 1.0
    └── sqlparse == 0.3.0  # Outdated constraint

ERROR: Conflicting versions of sqlparse
```

**Solutions:**

1. Update mypackage to remove strict constraint
2. Contact mypackage maintainer
3. Fork and fix mypackage (last resort)

### Dependency Resolution Best Practices

1. **Use flexible constraints**: `>=` instead of `~=` or `^`
2. **Avoid upper bounds**: Unless you have proof of incompatibility
3. **Update regularly**: Don't let dependencies get too stale
4. **Test broadly**: Use tools like tox to test multiple dependency versions
5. **Monitor resolution time**: If resolution is slow, simplify constraints
6. **Use lock files**: For reproducible builds
7. **Virtual environments**: Always isolate projects

---

## Security Scanning Integration

### Security Scanning Tools for Python (2024)

| Tool           | Type                    | Database               | CLI | CI/CD | SBOM | License                  |
| -------------- | ----------------------- | ---------------------- | --- | ----- | ---- | ------------------------ |
| **Safety CLI** | Dependency              | Safety DB (52k+ vulns) | ✅  | ✅    | ✅   | Open Source + Commercial |
| **pip-audit**  | Dependency              | OSV (Google)           | ✅  | ✅    | ✅   | Open Source (Apache 2.0) |
| **Bandit**     | Code (SAST)             | CWE patterns           | ✅  | ✅    | ❌   | Open Source (Apache 2.0) |
| **Trivy**      | Container + Deps        | Multiple sources       | ✅  | ✅    | ✅   | Open Source (Apache 2.0) |
| **Snyk**       | Deps + Code + Container | Snyk DB                | ✅  | ✅    | ✅   | Commercial (Free tier)   |

### Recommended Tools

#### 1. Safety CLI (Dependency Scanning)

**Best for:** Comprehensive dependency vulnerability scanning

**Installation:**

```bash
uv pip install safety
```

**Usage:**

```bash
# Scan installed packages
safety check

# Scan requirements file
safety check -r requirements.txt

# JSON output for CI
safety check --json --output safety-report.json

# Scan pyproject.toml (Safety CLI 3+)
safety scan
```

**Features:**

- Industry's most comprehensive vulnerability database (52k+ vulnerabilities)
- Detects malicious packages
- SBOM generation
- Python >= 3.9 required

**CI Integration:**

```yaml
# .github/workflows/security.yml
name: Security Scan
on: [push, pull_request]

jobs:
  safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv pip install safety
      - run: safety check --json --output safety-report.json
      - uses: actions/upload-artifact@v4
        with:
          name: safety-report
          path: safety-report.json
```

#### 2. pip-audit (Open Source Alternative)

**Best for:** Open-source dependency scanning with OSV database

**Installation:**

```bash
uv pip install pip-audit
```

**Usage:**

```bash
# Scan installed packages
pip-audit

# Scan requirements file
pip-audit -r requirements.txt

# Scan pyproject.toml
pip-audit --desc on

# Fix vulnerabilities automatically
pip-audit --fix
```

**Features:**

- Uses Google's OSV (Open Source Vulnerabilities) database
- Free and open source
- Automatic fixes with --fix
- CVE identifiers

**CI Integration:**

```yaml
# .github/workflows/security.yml
- name: Install pip-audit
  run: uv pip install pip-audit

- name: Scan dependencies
  run: pip-audit --desc on
```

#### 3. Bandit (Code Scanning)

**Best for:** Static analysis of Python code for security issues

**Installation:**

```bash
uv pip install bandit
```

**Usage:**

```bash
# Scan all Python files
bandit -r src/

# Exclude tests
bandit -r src/ --exclude tests/

# JSON output
bandit -r src/ -f json -o bandit-report.json
```

**Features:**

- Detects common security issues (SQL injection, hardcoded passwords, etc.)
- Configurable rules
- Integration with IDEs

**Common Checks:**

- Hardcoded passwords
- SQL injection
- Shell injection
- Insecure crypto
- Insecure temp files

**CI Integration:**

```yaml
- name: Install Bandit
  run: uv pip install bandit

- name: Run Bandit
  run: bandit -r src/ --format json --output bandit-report.json
```

#### 4. Trivy (Container + Dependency Scanning)

**Best for:** Docker image scanning with dependency checks

**Installation:**

```bash
# macOS
brew install trivy

# Linux
wget -qO - https://aquasecurity.github.io/trivy-repo/deb/public.key | sudo apt-key add -
echo "deb https://aquasecurity.github.io/trivy-repo/deb $(lsb_release -sc) main" | sudo tee /a/etc/apt/sources.list.d/trivy.list
sudo apt-get update && sudo apt-get install trivy
```

**Usage:**

```bash
# Scan Docker image
trivy image python:3.11-slim

# Scan requirements.txt
trivy fs --security-checks vuln requirements.txt

# Scan Poetry lock file
trivy fs --security-checks vuln poetry.lock

# Scan filesystem for secrets
trivy fs --scanners secret .
```

**Features:**

- Scans Docker images, filesystems, Git repos
- Detects OS packages, language dependencies, misconfigurations
- Finds secrets in code
- SBOM generation

**CI Integration:**

```yaml
- name: Run Trivy
  uses: aquasecurity/trivy-action@master
  with:
    scan-type: 'fs'
    scan-ref: '.'
    format: 'sarif'
    output: 'trivy-results.sarif'

- name: Upload Trivy results
  uses: github/codeql-action/upload-sarif@v2
  with:
    sarif_file: 'trivy-results.sarif'
```

### Security Scanning Strategy

#### 1. Pre-Commit Hooks (Local Development)

**Setup with pre-commit:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: '1.7.8'
    hooks:
      - id: bandit
        args: ['-c', 'pyproject.toml']
        exclude: ^tests/

  - repo: local
    hooks:
      - id: pip-audit
        name: pip-audit
        entry: pip-audit
        language: system
        pass_filenames: false
        always_run: true
```

**Benefits:**

- Catch issues before commit
- Fast feedback loop
- Prevent vulnerable code from reaching CI

#### 2. CI/CD Pipeline (GitHub Actions)

**Comprehensive security workflow:**

```yaml
# .github/workflows/security.yml
name: Security Scan

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 0 * * 0' # Weekly scan on Sundays

jobs:
  dependency-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install UV
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync

      - name: Run Safety
        run: |
          uv pip install safety
          safety check --json --output safety-report.json
        continue-on-error: true

      - name: Run pip-audit
        run: |
          uv pip install pip-audit
          pip-audit --desc on
        continue-on-error: true

      - name: Upload reports
        uses: actions/upload-artifact@v4
        with:
          name: security-reports
          path: |
            safety-report.json
            bandit-report.json

  code-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Run Bandit
        run: |
          pip install bandit
          bandit -r src/ -f json -o bandit-report.json

      - name: Upload Bandit report
        uses: actions/upload-artifact@v4
        with:
          name: bandit-report
          path: bandit-report.json

  container-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -t myapp:latest .

      - name: Run Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: 'myapp:latest'
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: 'trivy-results.sarif'
```

#### 3. Scheduled Scans (Weekly/Monthly)

**Add to GitHub Actions workflow:**

```yaml
on:
  schedule:
    - cron: '0 0 * * 0' # Every Sunday at midnight
```

**Benefits:**

- Catch newly disclosed vulnerabilities
- Monitor dependencies over time
- No manual intervention required

#### 4. Dependency Update Automation

**Use Renovate with security prioritization:**

```json
// renovate.json
{
  "extends": ["config:recommended"],
  "vulnerabilityAlerts": {
    "enabled": true,
    "labels": ["security"]
  },
  "packageRules": [
    {
      "matchUpdateTypes": ["patch"],
      "matchCurrentVersion": "!/^0/",
      "automerge": true,
      "automergeType": "pr",
      "automergeStrategy": "squash"
    },
    {
      "matchDatasources": ["pypi"],
      "matchPackagePatterns": ["*"],
      "groupName": "Python dependencies",
      "schedule": ["before 3am on Monday"]
    }
  ]
}
```

### Security Best Practices

1. **Scan Early, Scan Often**
   - Pre-commit hooks for immediate feedback
   - CI for every PR
   - Scheduled weekly scans

2. **Multiple Tools**
   - Use both Safety and pip-audit (different databases)
   - Combine dependency scanning (Safety) with code scanning (Bandit)
   - Container scanning for Docker images

3. **Automate Fixes**
   - Use `pip-audit --fix` for automatic updates
   - Configure Renovate/Dependabot for automated PRs
   - Test updates in CI before merging

4. **Monitor Continuously**
   - Enable GitHub Security Alerts
   - Subscribe to security advisories (PyPI, GitHub)
   - Review SBOM regularly

5. **Document Exceptions**
   ```toml
   # pyproject.toml
   [tool.safety]
   ignore-vulnerabilities = [
       "12345",  # False positive - not using affected feature
   ]
   ```

---

## PEP 751: Standard Lock File Format

### Overview

**PEP 751** proposes a standardized lock file format (`pylock.toml`) for the
Python ecosystem.

**Status:** Accepted March 2025 **Authors:** Brett Cannon **Format:**
TOML-based, human-readable, machine-generated

### Why PEP 751?

**The Problem:** Fragmented lock file ecosystem

- Poetry: `poetry.lock`
- pip-tools: `requirements.txt`
- PDM: `pdm.lock`
- UV: `uv.lock`
- Pipenv: `Pipfile.lock`

**Result:** Vendor lock-in, tool-specific workflows, no interoperability

**The Solution:** Standard format like:

- JavaScript: `package-lock.json`
- Rust: `Cargo.lock`
- Go: `go.sum`

### pylock.toml Format

**Example:**

```toml
version = "1.0"
requires-python = ">=3.11"

[[package]]
name = "anthropic"
version = "0.40.0"
source = { type = "index", url = "https://pypi.org/simple" }
dependencies = [
    "httpx >= 0.24.0, < 1.0.0",
    "pydantic >= 2.0.0",
]
extras = []
markers = ""

[[package.files]]
name = "anthropic"
version = "0.40.0"
file = { url = "https://files.pythonhosted.org/packages/.../anthropic-0.40.0-py3-none-any.whl", hash = "sha256:..." }

[[package]]
name = "httpx"
version = "0.27.0"
source = { type = "index", url = "https://pypi.org/simple" }
dependencies = []
extras = []
markers = ""

[[package.files]]
name = "httpx"
version = "0.27.0"
file = { url = "https://files.pythonhosted.org/packages/.../httpx-0.27.0-py3-none-any.whl", hash = "sha256:..." }
```

### Key Features

1. **Version Field**: `version = "1.0"` - Allows future format evolution
2. **Python Constraint**: `requires-python = ">=3.11"`
3. **Flat Package List**: Array of `[[package]]` entries
4. **Cryptographic Hashes**: Included for all files (security)
5. **Source Information**: Where package came from (PyPI, URL, path)
6. **Dependency Graph**: Each package lists its dependencies
7. **Markers**: Platform-specific dependencies (e.g., `sys_platform == 'win32'`)

### Adoption Status (2025)

**Current State:**

- ✅ PEP Accepted (March 2025)
- ⏳ Tool implementation in progress
- ❌ No tool fully supports pylock.toml yet

**Expected Timeline:**

- **2025**: Tool authors begin implementation
- **2026**: Early adopters support pylock.toml export
- **2027+**: Widespread adoption

**UV's Stance:**

> "PEP 751-style pylock.toml files are not yet sufficient to replace uv.lock."

**Poetry's Stance:**

> Will implement PEP 751 as an export format, but poetry.lock remains primary.

### Benefits

1. **Interoperability**: Switch between tools without losing lock file
2. **Security**: Standardized hash verification
3. **Tooling**: Better ecosystem support (linters, auditors, analyzers)
4. **Transparency**: Human-readable format for auditing

### Limitations

1. **Not Yet Supported**: No tool fully implements PEP 751 today
2. **Migration Path**: Existing projects have millions of lock files in other
   formats
3. **Tool-Specific Features**: Each tool has unique features not in standard

### Recommendation for This Project

**For 2025:**

- ✅ Use UV with `uv.lock` (current best practice)
- ⏳ Monitor PEP 751 adoption
- 🔄 Plan migration when tools support export

**Future (2026+):**

- Consider migrating to `pylock.toml` when:
  - UV/Poetry/PDM support export
  - Ecosystem tooling stabilizes
  - Benefits outweigh migration costs

---

## Recommendations for This Project

### Executive Recommendations

Based on the research, here are the **specific recommendations** for the
Autonomous AI Development Platform:

#### 1. Use UV as Primary Tool ✅

**Why:**

- 10-100x faster than Poetry (Rust-based)
- Native monorepo support (workspace feature)
- Modern Python packaging (PEP 621, PEP 735)
- Single lock file for entire workspace
- Built-in Python version management
- No migration needed (greenfield project)

**Action:**

```bash
# Already in project
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### 2. Dependency Pinning Strategy

**For libraries (if published to PyPI):**

```toml
[project]
dependencies = [
    "anthropic >= 0.40.0",           # No upper bound
    "langgraph >= 0.2.0",            # No upper bound
]
```

**For applications (services/python_agents):**

```toml
[project]
dependencies = [
    "fastapi >= 0.100.0",            # Flexible lower bound
    "sqlalchemy >= 2.0.0",           # Major version specified
]
```

**Plus uv.lock for exact versions in deployment**

#### 3. Monorepo Structure

**Current structure (good, keep it):**

```
autonomous-ai-platform/
├── pyproject.toml           # Root workspace
├── uv.lock                  # Single lock file
├── .python-version          # Python 3.11
├── packages/
│   ├── agent-core/
│   │   └── pyproject.toml
│   ├── research-engine/
│   │   └── pyproject.toml
│   └── execution-engine/
│       └── pyproject.toml
└── services/
    └── python_agents/
        └── pyproject.toml
```

**Root pyproject.toml:**

```toml
[project]
name = "autonomous-ai-platform"
version = "0.1.0"
requires-python = ">=3.11"
description = "Autonomous AI Development Platform"

[tool.uv.workspace]
members = [
    "packages/agent-core",
    "packages/research-engine",
    "packages/execution-engine",
    "services/python_agents",
]

[project.optional-dependencies]
# Shared dev dependencies
dev = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
    "ruff >= 0.6.0",
    "mypy >= 1.10.0",
    "pre-commit >= 3.6.0",
]
```

**Package pyproject.toml (example for research-engine):**

```toml
[project]
name = "research-engine"
version = "0.1.0"
requires-python = ">=3.11"
description = "Research paper discovery and algorithm extraction"

dependencies = [
    # Internal workspace dependencies (no version needed)
    "agent-core",

    # External dependencies (flexible constraints)
    "anthropic >= 0.40.0",
    "pymupdf >= 1.24.0",
    "arxiv >= 2.1.0",
]

[tool.uv.sources]
agent-core = { workspace = true }

[project.optional-dependencies]
dev = [
    "pytest >= 8.0.0",
    "pytest-mock >= 3.12.0",
]
```

#### 4. Version Constraint Operators

**Use this pattern consistently:**

```toml
[project]
dependencies = [
    # ✅ Recommended: >= for flexibility
    "anthropic >= 0.40.0",
    "langgraph >= 0.2.0",
    "pydantic >= 2.0.0",

    # ⚠️ Use only when necessary: != for broken versions
    "requests >= 2.28.0, != 2.31.1",  # CVE in 2.31.1

    # ❌ Avoid: Upper bounds (unless proven incompatible)
    # "anthropic >= 0.40.0, < 1.0.0",  # DON'T DO THIS
]
```

#### 5. Optional Dependencies Structure

**Organize by feature and environment:**

```toml
[project.optional-dependencies]
# Feature-based extras
arxiv = [
    "arxiv >= 2.1.0",
    "pymupdf >= 1.24.0",
]

acm = [
    "beautifulsoup4 >= 4.12.0",
]

all-research = [
    "research-engine[arxiv,acm]",
]

# Development extras
test = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
    "pytest-mock >= 3.12.0",
]

lint = [
    "ruff >= 0.6.0",
]

type-check = [
    "mypy >= 1.10.0",
    "types-requests >= 2.31.0",
]

dev = [
    "research-engine[test,lint,type-check]",
    "ipdb >= 0.13.0",
    "pre-commit >= 3.6.0",
]
```

#### 6. Security Scanning (CRITICAL)

**Implement multi-layered security:**

**A. Pre-commit Hooks:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/PyCQA/bandit
    rev: '1.7.8'
    hooks:
      - id: bandit
        args: ['-r', 'services/', '-r', 'packages/']
        exclude: ^tests/
```

**B. GitHub Actions Workflow:**

```yaml
# .github/workflows/security.yml
name: Security Scan

on:
  push:
    branches: [main]
  pull_request:
  schedule:
    - cron: '0 0 * * 0' # Weekly

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install UV
        uses: astral-sh/setup-uv@v4

      - name: Install dependencies
        run: uv sync

      - name: Run pip-audit
        run: |
          uv pip install pip-audit
          pip-audit --desc on
        continue-on-error: true

      - name: Run Bandit
        run: |
          uv pip install bandit
          bandit -r services/ -r packages/ -f json -o bandit-report.json
        continue-on-error: true

      - name: Upload reports
        uses: actions/upload-artifact@v4
        with:
          name: security-reports
          path: |
            bandit-report.json
```

**C. Renovate Configuration:**

```json
// renovate.json (already exists)
{
  "extends": ["config:recommended"],
  "vulnerabilityAlerts": {
    "enabled": true,
    "labels": ["security", "dependencies"]
  },
  "packageRules": [
    {
      "matchDatasources": ["pypi"],
      "groupName": "Python dependencies",
      "schedule": ["before 3am on Monday"]
    }
  ]
}
```

#### 7. Lock File Management

**Best practices for this project:**

1. **Commit uv.lock to Git** ✅

   ```bash
   git add uv.lock
   git commit -m "chore: update dependencies"
   ```

2. **Regenerate weekly**

   ```bash
   # Update all dependencies to latest compatible versions
   uv lock --upgrade
   ```

3. **CI check for stale lock file**

   ```yaml
   # .github/workflows/ci.yml
   - name: Check lock file is up-to-date
     run: uv lock --check
   ```

4. **Document lock file updates**

   ```bash
   # Good commit message
   git commit -m "chore(deps): update dependencies (2025-11-14)

   - anthropic: 0.40.0 → 0.41.0
   - langgraph: 0.2.0 → 0.2.1
   - pytest: 8.0.0 → 8.1.0"
   ```

#### 8. Development Workflow

**Recommended commands for developers:**

```bash
# Initial setup
uv sync --extra dev

# Add dependency to specific package
cd packages/research-engine
uv add arxiv

# Add dev dependency
uv add --dev pytest-mock

# Run tests
pytest packages/research-engine/tests/

# Update dependencies
uv lock --upgrade

# Check for vulnerabilities
uv pip install pip-audit && pip-audit
```

#### 9. Documentation Updates

**Update CLAUDE.md with these additions:**

````markdown
### Dependency Management

**Tool:** UV (Rust-based, 10-100x faster than pip/Poetry)

**Structure:**

- Root workspace: `pyproject.toml` + `uv.lock`
- Package dependencies: No upper bounds (library best practices)
- Lock file: Single `uv.lock` for entire monorepo

**Adding Dependencies:**

```bash
cd packages/<package-name>
uv add <dependency>
```
````

**Security Scanning:**

- Pre-commit: Bandit (code scanning)
- CI: pip-audit (dependency vulnerabilities)
- Weekly: Automated scans via GitHub Actions

````

#### 10. Migration Path (if needed later)

**If considering Poetry → UV migration:**

```bash
# UV reads Poetry format natively
uv sync  # Reads poetry.lock and pyproject.toml

# Generate uv.lock
uv lock

# Verify
uv sync
pytest

# Remove Poetry files (optional)
rm poetry.lock
````

### Implementation Checklist

- [ ] Create root `pyproject.toml` with workspace configuration
- [ ] Update package `pyproject.toml` files with flexible constraints
- [ ] Generate `uv.lock` with `uv lock`
- [ ] Configure optional dependencies (dev, test, lint, type-check)
- [ ] Set up pre-commit hooks with Bandit
- [ ] Create security scanning GitHub Actions workflow
- [ ] Document dependency management in CLAUDE.md
- [ ] Add CI check for stale lock file
- [ ] Configure Renovate for automated updates
- [ ] Add security scanning to weekly schedule

---

## Code Examples

### Example 1: Complete Package Configuration

**packages/research-engine/pyproject.toml:**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "research-engine"
version = "0.1.0"
description = "Research paper discovery and algorithm extraction"
requires-python = ">=3.11"
authors = [
    {name = "Your Name", email = "you@example.com"}
]
readme = "README.md"
license = {text = "MIT"}

# Production dependencies (flexible constraints, no upper bounds)
dependencies = [
    # Internal workspace dependency
    "agent-core",

    # AI/ML dependencies
    "anthropic >= 0.40.0",
    "langgraph >= 0.2.0",

    # Research APIs
    "arxiv >= 2.1.0",

    # PDF processing
    "pymupdf >= 1.24.0",

    # Data processing
    "pydantic >= 2.0.0",
    "pandas >= 2.0.0",
]

# Specify workspace sources
[tool.uv.sources]
agent-core = { workspace = true }

# Optional dependencies organized by feature and environment
[project.optional-dependencies]
# Research source integrations
arxiv = [
    "arxiv >= 2.1.0",
    "pymupdf >= 1.24.0",
]

acm = [
    "beautifulsoup4 >= 4.12.0",
    "lxml >= 5.0.0",
]

all-sources = [
    "research-engine[arxiv,acm]",
]

# Testing dependencies
test = [
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
    "pytest-mock >= 3.12.0",
]

# Linting dependencies
lint = [
    "ruff >= 0.6.0",
]

# Type checking dependencies
type-check = [
    "mypy >= 1.10.0",
    "types-requests >= 2.31.0",
    "pandas-stubs >= 2.0.0",
]

# All development dependencies
dev = [
    "research-engine[test,lint,type-check]",
    "ipdb >= 0.13.0",
    "pre-commit >= 3.6.0",
]

[project.urls]
Homepage = "https://github.com/yourusername/autonomous-ai-platform"
Documentation = "https://github.com/yourusername/autonomous-ai-platform#readme"
Repository = "https://github.com/yourusername/autonomous-ai-platform"
Issues = "https://github.com/yourusername/autonomous-ai-platform/issues"

# Ruff configuration
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]
ignore = []

# Mypy configuration
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true

# Pytest configuration
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
addopts = "-v --cov=src --cov-report=term-missing"

# Coverage configuration
[tool.coverage.run]
source = ["src"]
omit = ["*/tests/*", "*/test_*.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### Example 2: Root Workspace Configuration

**pyproject.toml (root):**

```toml
[project]
name = "autonomous-ai-platform"
version = "0.1.0"
description = "Autonomous AI Development Platform with research integration"
requires-python = ">=3.11"
authors = [
    {name = "Praveen Kanna", email = "your@email.com"}
]

# Define workspace members
[tool.uv.workspace]
members = [
    "packages/agent-core",
    "packages/research-engine",
    "packages/execution-engine",
    "services/python_agents",
]

# Workspace-wide development dependencies
[project.optional-dependencies]
dev = [
    # Testing
    "pytest >= 8.0.0",
    "pytest-cov >= 4.1.0",
    "pytest-asyncio >= 0.23.0",
    "pytest-mock >= 3.12.0",

    # Linting & formatting
    "ruff >= 0.6.0",

    # Type checking
    "mypy >= 1.10.0",

    # Git hooks
    "pre-commit >= 3.6.0",

    # Debugging
    "ipdb >= 0.13.0",
]

# Security scanning
security = [
    "safety >= 3.0.0",
    "pip-audit >= 2.7.0",
    "bandit >= 1.7.0",
]

# Documentation
docs = [
    "sphinx >= 7.0.0",
    "sphinx-rtd-theme >= 2.0.0",
]

# All dev tools
dev-all = [
    "autonomous-ai-platform[dev,security,docs]",
]

# Ruff configuration (workspace-wide)
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "W",   # pycodestyle warnings
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # Allow unused imports in __init__.py
"tests/**" = ["S101"]     # Allow assertions in tests

# Mypy configuration (workspace-wide)
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
no_implicit_optional = true
strict_equality = true

# Pytest configuration (workspace-wide)
[tool.pytest.ini_options]
testpaths = ["packages", "services"]
python_files = ["test_*.py", "*_test.py"]
addopts = """
    -v
    --cov=packages
    --cov=services
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=90
"""

# Coverage configuration
[tool.coverage.run]
source = ["packages", "services"]
omit = [
    "*/tests/*",
    "*/test_*.py",
    "*/__init__.py",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]

# Bandit configuration
[tool.bandit]
exclude_dirs = ["tests", "venv", ".venv"]
skips = ["B101"]  # Allow assertions
```

### Example 3: Pre-Commit Configuration

**.pre-commit-config.yaml:**

```yaml
# Python 3.11 required
default_language_version:
  python: python3.11

repos:
  # Ruff - Fast Python linter
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      # Run linter
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      # Run formatter
      - id: ruff-format

  # Mypy - Type checking
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies:
          - types-requests
          - pydantic
        args: [--config-file=pyproject.toml]

  # Bandit - Security linting
  - repo: https://github.com/PyCQA/bandit
    rev: '1.7.8'
    hooks:
      - id: bandit
        args: ['-c', 'pyproject.toml']
        exclude: ^tests/

  # Standard pre-commit hooks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=1000']
      - id: check-merge-conflict
      - id: debug-statements

  # Local hooks
  - repo: local
    hooks:
      # pip-audit - Dependency vulnerability scanning
      - id: pip-audit
        name: pip-audit
        entry: uv run pip-audit
        language: system
        pass_filenames: false
        always_run: true

      # Pytest - Run tests
      - id: pytest
        name: pytest
        entry: uv run pytest
        language: system
        pass_filenames: false
        always_run: true
        args: [--cov, --cov-fail-under=90]
```

### Example 4: GitHub Actions Security Workflow

**.github/workflows/security.yml:**

```yaml
name: Security Scan

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    # Weekly scan every Sunday at midnight UTC
    - cron: '0 0 * * 0'
  workflow_dispatch: # Allow manual trigger

jobs:
  dependency-scan:
    name: Dependency Security Scan
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install UV
        uses: astral-sh/setup-uv@v4
        with:
          version: 'latest'

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run pip-audit (OSV database)
        run: |
          uv pip install pip-audit
          pip-audit --desc on --format json --output pip-audit-report.json
        continue-on-error: true

      - name: Run Safety (Safety DB)
        run: |
          uv pip install safety
          safety check --json --output safety-report.json
        continue-on-error: true

      - name: Upload dependency scan reports
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: dependency-scan-reports
          path: |
            pip-audit-report.json
            safety-report.json
          retention-days: 30

  code-scan:
    name: Code Security Scan (SAST)
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install UV
        uses: astral-sh/setup-uv@v4

      - name: Install Bandit
        run: uv pip install bandit[toml]

      - name: Run Bandit
        run: |
          bandit -r packages/ services/ \
            -f json \
            -o bandit-report.json \
            -c pyproject.toml
        continue-on-error: true

      - name: Upload Bandit report
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: bandit-report
          path: bandit-report.json
          retention-days: 30

  container-scan:
    name: Docker Image Security Scan
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Build Docker image (if Dockerfile exists)
        run: |
          if [ -f Dockerfile ]; then
            docker build -t autonomous-ai-platform:${{ github.sha }} .
          fi

      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        if: hashFiles('Dockerfile') != ''
        with:
          image-ref: 'autonomous-ai-platform:${{ github.sha }}'
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'

      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v2
        if: hashFiles('Dockerfile') != ''
        with:
          sarif_file: 'trivy-results.sarif'

      - name: Upload Trivy report
        uses: actions/upload-artifact@v4
        if: always() && hashFiles('Dockerfile') != ''
        with:
          name: trivy-report
          path: trivy-results.sarif
          retention-days: 30

  security-summary:
    name: Security Summary
    runs-on: ubuntu-latest
    needs: [dependency-scan, code-scan, container-scan]
    if: always()

    steps:
      - name: Download all reports
        uses: actions/download-artifact@v4
        with:
          path: security-reports

      - name: Display summary
        run: |
          echo "## Security Scan Summary" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "✅ Dependency scan completed" >> $GITHUB_STEP_SUMMARY
          echo "✅ Code scan completed" >> $GITHUB_STEP_SUMMARY
          echo "✅ Container scan completed (if applicable)" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "📊 View detailed reports in job artifacts" >> $GITHUB_STEP_SUMMARY
```

### Example 5: Development Commands

**Makefile (optional convenience wrapper):**

```makefile
.PHONY: help install dev test lint type-check security clean

help:  ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:  ## Install production dependencies
	uv sync

dev:  ## Install with development dependencies
	uv sync --extra dev

test:  ## Run tests with coverage
	uv run pytest --cov --cov-report=html --cov-report=term

test-watch:  ## Run tests in watch mode
	uv run pytest-watch

lint:  ## Run linter
	uv run ruff check packages/ services/

lint-fix:  ## Run linter with auto-fix
	uv run ruff check --fix packages/ services/
	uv run ruff format packages/ services/

type-check:  ## Run type checker
	uv run mypy packages/ services/

security:  ## Run security scans
	uv pip install pip-audit bandit
	pip-audit --desc on
	bandit -r packages/ services/ -c pyproject.toml

pre-commit:  ## Run all pre-commit checks
	uv run pre-commit run --all-files

update:  ## Update dependencies
	uv lock --upgrade

update-package:  ## Update specific package (usage: make update-package PKG=anthropic)
	uv add --upgrade $(PKG)

clean:  ## Clean build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

workspace-status:  ## Show workspace package versions
	uv tree

add:  ## Add dependency (usage: make add PKG=requests)
	cd packages/agent-core && uv add $(PKG)

add-dev:  ## Add dev dependency (usage: make add-dev PKG=pytest)
	cd packages/agent-core && uv add --dev $(PKG)
```

**Usage:**

```bash
# Install for development
make dev

# Run tests
make test

# Run all checks (lint + type-check + security + test)
make lint && make type-check && make security && make test

# Or use pre-commit for all checks
make pre-commit

# Update dependencies weekly
make update

# Add new dependency to agent-core
cd packages/agent-core
uv add anthropic

# Check workspace status
make workspace-status
```

---

## References

### Official Python Packaging Documentation

1. **Python Packaging User Guide** - https://packaging.python.org/
   - Writing pyproject.toml:
     https://packaging.python.org/en/latest/guides/writing-pyproject-toml/
   - Managing Dependencies:
     https://packaging.python.org/en/latest/tutorials/managing-dependencies/
   - Dependency Specifiers:
     https://packaging.python.org/en/latest/specifications/dependency-specifiers/

2. **PEPs (Python Enhancement Proposals)**
   - PEP 440 (Version Identification): https://peps.python.org/pep-0440/
   - PEP 508 (Dependency Specification): https://peps.python.org/pep-0508/
   - PEP 621 (Project Metadata): https://peps.python.org/pep-0621/
   - PEP 631 (Dependency Specification in pyproject.toml):
     https://peps.python.org/pep-0631/
   - PEP 735 (Dependency Groups): https://peps.python.org/pep-0735/ (Draft)
   - PEP 751 (Lock File Format): https://peps.python.org/pep-0751/

### Tool Documentation

3. **UV**
   - Official Docs: https://docs.astral.sh/uv/
   - GitHub: https://github.com/astral-sh/uv
   - Python UV Guide (DataCamp): https://www.datacamp.com/tutorial/python-uv

4. **Poetry**
   - Official Docs: https://python-poetry.org/docs/
   - pyproject.toml Reference: https://python-poetry.org/docs/pyproject/
   - Dependency Specification:
     https://python-poetry.org/docs/dependency-specification/

5. **pip-tools**
   - GitHub: https://github.com/jazzband/pip-tools
   - Documentation: https://pip-tools.readthedocs.io/

6. **pip**
   - Dependency Resolution:
     https://pip.pypa.io/en/stable/topics/dependency-resolution/

### Security Tools

7. **Safety CLI**
   - Official Site: https://safetycli.com/
   - PyPI: https://pypi.org/project/safety/
   - GitHub: https://github.com/pyupio/safety

8. **pip-audit**
   - GitHub: https://github.com/pypa/pip-audit
   - PyPI: https://pypi.org/project/pip-audit/

9. **Bandit**
   - GitHub: https://github.com/PyCQA/bandit
   - PyPI: https://pypi.org/project/bandit/

10. **Trivy**
    - Official Site: https://trivy.dev/
    - GitHub: https://github.com/aquasecurity/trivy
    - Documentation: https://aquasecurity.github.io/trivy/

### Community Articles & Discussions

11. **Should You Use Upper Bound Version Constraints?**
    - Article: https://iscinumpy.dev/post/bound-version-constraints/
    - Author: Henry Schreiner
    - Last Updated: May 10, 2024

12. **Python Monorepo Articles**
    - Tweag: https://www.tweag.io/blog/2023-04-04-python-monorepo-1/
    - Medium (Masashi Takanobu):
      https://medium.com/@mtakanobu2/python-monorepo-centralizing-multiple-projects-and-sharing-code-3c1ab496340a
    - LlamaIndex:
      https://www.llamaindex.ai/blog/python-tooling-at-scale-llamaindex-s-monorepo-overhaul

13. **Tool Comparisons (2024-2025)**
    - Loopwerk (Poetry vs UV):
      https://www.loopwerk.io/articles/2024/python-poetry-vs-uv/
    - Medium (Pip vs Poetry vs UV):
      https://dimasyotama.medium.com/navigating-the-python-packaging-landscape-pip-vs-poetry-vs-uv-a-developers-guide-49a9c93caf9c
    - Medium (Poetry vs UV 2025):
      https://medium.com/@hitorunajp/poetry-vs-uv-which-python-package-manager-should-you-use-in-2025-4212cb5e0a14

14. **PEP 751 Coverage**
    - Python Developer Tooling Handbook:
      https://pydevtools.com/handbook/explanation/what-is-pep-751/
    - InfoWorld Analysis:
      https://www.infoworld.com/article/3951671/understand-pythons-new-lock-file-format.html
    - Developer Tech News:
      https://www.developer-tech.com/news/python-standardised-lock-file-format-pep-751/

### GitHub Repositories (Examples)

15. **Python Monorepo Templates**
    - https://github.com/niqodea/python-monorepo
    - https://github.com/matanby/python-monorepo-template

16. **Security Tools**
    - https://github.com/pyupio/safety
    - https://github.com/pypa/pip-audit
    - https://github.com/PyCQA/bandit
    - https://github.com/aquasecurity/trivy

### Stack Overflow Discussions

17. **Dependency Management Questions**
    - Tilde Equals Operator:
      https://stackoverflow.com/questions/39590187/in-requirements-txt-what-does-tilde-equals-mean
    - Requirements.txt vs pyproject.toml:
      https://stackoverflow.com/questions/74508024/is-requirements-txt-still-needed-when-using-pyproject-toml
    - Optional Dependencies:
      https://stackoverflow.com/questions/71386332/how-do-i-specify-extra-bracket-dependencies-in-a-pyproject-toml

### Blogs & Opinion Pieces

18. **Hynek Schlawack**
    - Recursive Optional Dependencies:
      https://hynek.me/articles/python-recursive-optional-dependencies/

19. **Han Xiao**
    - Managing extras_require:
      https://hanxiao.io/2019/11/07/A-Better-Practice-for-Managing-extras-require-Dependencies-in-Python/

20. **Python Packaging Guides**
    - Better Stack Community:
      https://betterstack.com/community/guides/scaling-python/pyproject-explained/
    - Real Python: https://realpython.com/python-pyproject-toml/

---

**End of Research Report**

**Document Version:** 1.0 **Last Updated:** 2025-11-14 **Total Sources:** 50+
web pages, articles, PEPs, and documentation sites **Research Depth:** 13
comprehensive web searches across 8 major topic areas
