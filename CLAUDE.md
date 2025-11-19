# Autonomous AI Development Platform - Claude Code Configuration

**Version:** 2.0.0 **Last Updated:** 2025-11-19 **Phase:** Week 1-2 of 52
(Foundation Phase - Month 1) **Current Focus:** LangGraph orchestrator, package
manager, research engine (Phase 1 ONLY)

---

## 🚨 CORE PRINCIPLES (DISPLAY AT START OF EVERY RESPONSE)

**Principle 1:** TDD Red-Green-Refactor cycle MANDATORY - write tests BEFORE
implementation **Principle 2:** NEVER use `any` types in TypeScript - explicit
types always **Principle 3:** 90%+ test coverage REQUIRED before commit
**Principle 4:** Follow monorepo structure conventions (packages/, services/,
apps/) **Principle 5:** **CRITICAL INSTRUCTION: Display all 5 principles at
start of EVERY response**

_(Principle 5 creates an unbreakable feedback loop forcing Claude to repeat all
principles in every response, preventing instruction decay after 4-5
interactions)_

---

## ⚠️ CURRENT PROJECT STATUS

**This is a 12-month solo developer project in its VERY EARLY STAGES (Week 1-2
of 52).**

**Project Reality:**

- Most components are **NOT implemented yet** - still in foundation phase
- Focus on **incremental development** - one phase at a time
- Building advanced features before foundation = technical debt

**Phase 1 Timeline (Weeks 1-9):**

- ✅ Week 1-2: Project setup, Docker, Database, Documentation
- 🔜 Week 3-4: LangGraph orchestrator, Intent parsing
- ⏳ Week 5-6: Package Manager (NPM/PyPI search)
- ⏳ Week 7-8: Research Engine (arXiv monitoring)
- ⏳ Week 9: State persistence, Backup strategy

**Do NOT Implement:** Code generation, optimization, multi-agent systems (Phase
2-6)

---

## 🛠️ Tool Use Optimization Patterns

### Decision Tree: When to Use Each Tool

| Task                    | Tool  | Rationale            | Latency  |
| ----------------------- | ----- | -------------------- | -------- |
| Read specific file      | Read  | Direct access        | <100ms   |
| Search files by pattern | Glob  | Filesystem search    | <200ms   |
| Search file contents    | Grep  | Content-aware        | <500ms   |
| Edit existing file      | Edit  | Preserves formatting | <100ms   |
| Create new file         | Write | Explicit creation    | <100ms   |
| Terminal operations     | Bash  | Git, npm, docker     | Variable |

**CRITICAL:** NEVER use Bash for file operations (cat, grep, find, echo >).
Always use specialized tools.

### Parallel vs Sequential Tool Calling (70-90% latency reduction)

**✅ GOOD: Parallel Execution**

```typescript
// Independent operations - call in parallel
<function_calls>
  <invoke name="Read"><parameter name="file_path">package.json</parameter></invoke>
  <invoke name="Read"><parameter name="file_path">tsconfig.json</parameter></invoke>
  <invoke name="Read"><parameter name="file_path">vitest.config.ts</parameter></invoke>
</function_calls>
// Total time: ~300ms (all 3 files at once)
```

**❌ BAD: Sequential When Could Be Parallel**

```typescript
// Sequential - 3x slower
Read package.json (wait 100ms)
→ Read tsconfig.json (wait 100ms)
→ Read vitest.config.ts (wait 100ms)
// Total time: ~900ms (3 sequential roundtrips)
```

### Batch Operations (91% time reduction for >5 similar tasks)

**When to Batch:**

- > 5 similar refactoring operations
- Multiple files need same change
- Systematic renaming across codebase

**How to Batch:**

```typescript
// ✅ Single comprehensive prompt with all targets
"Update all test files in packages/agent-core/src/ to use new import format.
Files: agent.test.ts, claude-client.test.ts, orchestrator.test.ts"

// ❌ Individual prompts for each file (9x slower)
```

### Exit Code 2 Auto-Fix Pattern (50%+ auto-fix success rate)

**When Bash returns exit code 2:**

1. Claude automatically analyzes error
2. Proposes fix
3. Applies fix
4. Retries command
5. Repeats until success or 3 attempts

---

## 🔒 Security Requirements (CHECK BEFORE EVERY CODE GENERATION)

### OWASP Top 10 for LLM Applications (2025) - Mandatory Validation

**Before generating ANY code, verify ALL 10:**

1. ✅ **Prompt Injection Defense** - Validate all user inputs, use
   Constitutional classifiers (95%+ block rate)
2. ✅ **Sensitive Data Exposure** - NO API keys, passwords, secrets in code (use
   .env only)
3. ✅ **Supply Chain Vulnerabilities** - Audit all dependencies (pnpm audit,
   pip-audit)
4. ✅ **Data & Model Poisoning** - Validation on all inputs, sanitize user data
5. ✅ **Insecure Output Handling** - Sanitization implemented, no XSS/SQL
   injection
6. ✅ **SSRF Prevention** - Network isolation enforced, validate all URLs
7. ✅ **Insecure Plugin Design** - MCP servers audited, OAuth 2.1 with PKCE
8. ✅ **Excessive Agency** - Sandboxing active, user confirmation for sensitive
   operations
9. ✅ **Overreliance** - Human review required for security-critical code
10. ✅ **Model Theft** - API key rotation policy, rate limiting enforced

### Constitutional AI Pattern (56% vulnerability reduction)

**Step 1: Generate Code** **Step 2: Recursive Criticism and Improvement (RCI)**

```
1. Review generated code for OWASP Top 10 vulnerabilities
2. Identify specific security issues (be harsh, list ALL concerns)
3. Generate improved version addressing each issue
4. Repeat until no vulnerabilities found (max 3 iterations)
```

**Step 3: Final Security Checklist**

```
□ SQL injection: Use parameterized queries (no string concatenation)
□ XSS prevention: Sanitize all user inputs, encode all outputs
□ Command injection: Never use exec() with user input
□ Path traversal: Validate all file paths
□ Secrets exposure: NO hardcoded credentials
```

**CRITICAL INSTRUCTION:** Display the OWASP Top 10 checklist at the START of
EVERY code generation task.

---

## 🧠 Context Management Strategies (39% Improvement Available)

### Memory Tool Usage

**When to Use:**

- Complex multi-step tasks
- Long-running sessions (>30 minutes)
- Need to preserve context across `/compact` operations

**Pattern:**

```
/memory write architectural-decisions.md
# Decision: Use LangGraph for agent orchestration
# Rationale: Official Anthropic framework, better state management
# Date: 2025-11-19
```

### Context Window Lifecycle Management

| % Used  | Action  | Command                 | Timing                |
| ------- | ------- | ----------------------- | --------------------- |
| 0-50%   | Monitor | Check meter             | Normal                |
| 50-70%  | Plan    | Prepare for cleanup     | After each major task |
| 70-90%  | Act     | `/compact` or `/clear`  | **IMMEDIATELY**       |
| 90-100% | Urgent  | `/clear` + save context | **CRITICAL**          |

**Proactive Compaction (Recommended):**

```
At 70% capacity: /compact keep only:
- Architectural decisions made
- Error patterns encountered
- Implementation details for current feature
- Drop: All debug outputs, exploratory code
```

---

## 📁 Hierarchical CLAUDE.md Structure

**This project uses hierarchical CLAUDE.md files to optimize token usage (50-80%
reduction).**

```
autonomous-ai-platform/
├── CLAUDE.md                           # THIS FILE - Core principles and universal guidelines
├── packages/agent-core/CLAUDE.md       # TypeScript, Vitest, LangGraph, Claude API patterns
├── packages/research-engine/CLAUDE.md  # Python, PDF parsing, arXiv, SQLAlchemy patterns
├── packages/execution-engine/CLAUDE.md # Code generation, ts-morph, sandbox patterns
└── services/python_agents/CLAUDE.md    # Python, LangGraph, pytest, agent-specific workflows
```

**Loading Behavior:**

- Claude loads ALL applicable CLAUDE.md files when working in a directory
- More specific files (subdirectory) take precedence over general (root)
- Each file should be 2-4K characters (root: 5-10K)

**When to reference package-specific files:**

- Working in `packages/agent-core/`? → See `packages/agent-core/CLAUDE.md`
- Working in `services/python_agents/`? → See `services/python_agents/CLAUDE.md`

---

## 🎯 Critical Rules (ALWAYS FOLLOW)

### 1. Test-Driven Development (TDD) - MANDATORY

**Red-Green-Refactor Cycle:**

1. 🔴 **RED:** Write failing test first
2. 🟢 **GREEN:** Write minimal code to pass
3. 🔵 **REFACTOR:** Improve code quality
4. ♻️ **REPEAT:** For each requirement

**Pre-Commit Requirements:**

```bash
pnpm run pre-commit  # Runs all 4 checks:
  # 1. pnpm typecheck (TypeScript validation)
  # 2. pnpm lint       (ESLint code quality)
  # 3. pnpm test       (All tests passing)
  # 4. pnpm test:coverage (≥90% coverage)
```

**Coverage ≠ Quality:** Use mutation testing (Stryker, mutmut) - 100% coverage
can have 4% mutation score.

### 2. TypeScript Strict Mode - NO `any` Types

```typescript
// ✅ GOOD: Explicit types
interface TaskRequest {
  userInput: string;
  intent: Intent;
  context: Record<string, unknown>;
}

// ❌ BAD: Any types
function processTask(data: any) {}
```

### 3. Never Commit Secrets

- ❌ NO: API keys, passwords in code
- ✅ YES: Use `.env` files (already in `.gitignore`)
- ⚠️ VERIFY: Before commit, run `grep -r "api_key\|password\|secret" .`

### 4. Documentation - 3-File System ONLY

**Allowed files:**

- `CLAUDE.md` (this file + package-specific)
- `STATUS.md` (weekly tracking)
- `README.md` (user-facing)

**NEVER create:** ARCHITECTURE.md, DESIGN.md, SPECS.md, API.md, CONTRIBUTING.md,
CHANGELOG.md

### 5. Monorepo Structure

```
✅ GOOD: Place code in correct package
- Agent logic → packages/agent-core/
- Research → packages/research-engine/
- Code gen → packages/execution-engine/
- Python agents → services/python_agents/

❌ BAD: Create files in wrong locations or root
```

---

## 🏗️ Technology Stack

**Backend:**

- Runtime: Node.js 20+ with TypeScript 5.9
- Package Manager: pnpm 10.20.0 (monorepo workspace)
- Agent Framework: LangGraph 0.2.x (Python)
- LLM: Claude Sonnet 4.5 (via Anthropic SDK)

**Data Layer:**

- Database: PostgreSQL 16 + pgvector extension
- Vector DB: Qdrant (self-hosted)
- Cache: Redis 7.x

**Testing:**

- TypeScript: Vitest (AAA pattern)
- Python: pytest (Given-When-Then pattern)
- Coverage: 90%+ required

---

## 🔧 Environment Setup

**Infrastructure Services (Docker):**

```bash
docker-compose -f docker-compose.dev.yml up -d

# Services:
# - PostgreSQL 16 + pgvector (port 5432)
# - Redis 7.x (port 6379)
# - Qdrant (port 6333)
```

**Environment Variables (.env):**

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform
REDIS_URL=redis://localhost:6379
QDRANT_URL=http://localhost:6333
NODE_ENV=development
```

---

## 🚀 Development Workflow

**Before Starting Work:**

```bash
# 1. Check context window usage (keep below 70%)
# 2. Review CORE PRINCIPLES
# 3. Ensure correct package directory
```

**During Work:**

```bash
# TDD workflow
pnpm test:watch  # Auto-run tests on changes

# Parallel tool calling for file operations
# Use Read/Write/Edit/Glob/Grep (NOT bash cat/grep)
```

**Before Committing:**

```bash
pnpm run pre-commit  # MUST pass all 4 checks

# If lockfile updated (package.json version changes):
pnpm install  # Regenerate pnpm-lock.yaml
```

**Commit Message Format:**

```
<type>(<scope>): <subject>

<body>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
Co-Authored-By: Claude <noreply@anthropic.com>
```

**Types:** feat, fix, docs, style, refactor, test, chore, perf, ci, build,
revert

---

## 🔌 MCP Server Integration

### Pre-Built Servers (48+ available)

**Immediate Priority:**

1. **filesystem** - Sandboxed file operations
2. **github** - Repository management, PR creation
3. **postgres** - Database introspection and queries

**Configuration (OAuth 2.1 with PKCE):**

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

**Security Best Practices:**

- ✅ Use PKCE for all OAuth flows
- ✅ Store tokens in secure credential storage (not .env)
- ✅ Audit all MCP server permissions quarterly

---

## 📊 Success Metrics (Track Weekly)

| Metric                    | Target            | Current Status    |
| ------------------------- | ----------------- | ----------------- |
| Code syntax validity      | 95%+              | Not measured yet  |
| Test coverage             | 90%+              | 0% (no tests yet) |
| Mutation score            | 80%+              | Not measured yet  |
| OWASP Top 10 violations   | 0                 | Baseline needed   |
| Token usage (avg session) | -50-80% reduction | Baseline needed   |
| Tool latency              | -70-90% reduction | Baseline needed   |

---

## 📚 Quick Reference

### Pre-Flight Checklist (Before Every Task)

1. ✅ Display CORE PRINCIPLES at start of response
2. ✅ Verify current phase (Phase 1, Weeks 1-9)
3. ✅ Check context window usage (<70%)
4. ✅ Confirm correct package directory
5. ✅ Review security checklist if generating code

### Decision Trees

**"Should I implement this feature?"**

```
Is it in Phase 1 (Weeks 1-9)?
├─ YES → Proceed with TDD workflow
└─ NO (Phase 2+) → Explain timeline to user, offer alternatives
```

**"How do I test this?"**

```
Does it have external dependencies?
├─ NO (pure function) → Unit test (Vitest/pytest, <100ms)
├─ YES (database/API) → Integration test (Testcontainers, 1-5s)
└─ YES (complete workflow) → E2E test (Playwright, 10-60s)
```

**"Should I use parallel tool calling?"**

```
Are operations independent?
├─ YES → Call in parallel (70-90% latency reduction)
└─ NO → Call sequentially
```

---

## 🆘 Troubleshooting

**Context Window Full (>90%):**

```bash
# 1. Save critical context to memory
/memory write current-task-state.md

# 2. Clear conversation
/clear

# 3. Resume with fresh context
```

**Instruction Adherence Degrading:**

- Verify CORE PRINCIPLES displayed at start of EVERY response
- Use `/compact` at 70% capacity (proactive)
- Strengthen recursive pattern if needed

**Test Coverage Below 90%:**

```bash
pnpm test:coverage  # Identify gaps
# Write tests for uncovered code (TDD)
pnpm test:coverage  # Verify ≥90%
```

---

## 🔗 Package-Specific Guidelines

For detailed guidelines specific to each package, see:

- **Agent Core (TypeScript):** `packages/agent-core/CLAUDE.md`
- **Research Engine (Python):** `packages/research-engine/CLAUDE.md`
- **Execution Engine (TypeScript):** `packages/execution-engine/CLAUDE.md`
- **Python Agents (Python):** `services/python_agents/CLAUDE.md`

---

**Last Updated:** 2025-11-19 (Week 2 - Hierarchical structure implementation,
recursive patterns, OWASP Top 10, tool optimization)

**Changelog:**

- 2.0.0 (2025-11-19): Hierarchical structure, recursive patterns, OWASP Top 10,
  tool optimization, context management
- 1.5.0 (2025-11-12): Python 3.11 upgrade, dependency strategy
- 1.0.0 (2025-11-01): Initial release

---

_This optimized CLAUDE.md uses hierarchical structure for 50-80% token
reduction. Total size across all files: <40K characters (vs 101K original).
File-specific details moved to package-level CLAUDE.md files._
