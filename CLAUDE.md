# Autonomous AI Development Platform - Documentation for Claude

## Table of Contents

1. [Project Changelog](#project-changelog)
2. [Project Overview](#project-overview)
3. [Architecture](#architecture)
4. [Project Structure](#project-structure)
5. [Database Schema](#database-schema)
6. [Implementation Timeline](#implementation-timeline)
7. [Core Features & Capabilities](#core-features--capabilities)
8. [Development Guide](#development-guide)
9. [Best Practices](#best-practices)
10. [Success Metrics](#success-metrics)
11. [Quick Reference for Claude](#quick-reference-for-claude)
12. [Appendix](#appendix)

---

## ⚠️ CURRENT PROJECT STATUS - READ THIS FIRST

> **🚨 CRITICAL: Read this section and "Critical Instructions for Claude" BEFORE
> making any changes 🚨**

**Phase:** Week 1-2 of 52 (Foundation Phase - Month 1 of 12-month timeline)
**Current Focus:** LangGraph orchestrator, package manager, research engine
(Phase 1 ONLY) **Do NOT Implement:** Code generation, optimization, multi-agent
systems (Phase 2-6)

**Project Reality:**

- This is a **12-month solo developer project** in its **very early stages**
- Most components are **NOT implemented yet** - still in foundation phase
- Focus on **incremental development** - one phase at a time
- Building advanced features before foundation = technical debt

**Mandatory Requirements:**

- ✅ **TDD Required:** Write tests FIRST (Red-Green-Refactor cycle)
- ✅ **Only 3 docs:** CLAUDE.md, STATUS.md, README.md (never create others)
- ✅ **Explicit types:** No `any` types in TypeScript
- ✅ **No secrets:** Never commit API keys or passwords
- ✅ **Phase 1 only:** Stay focused on current phase

**Next Step:** Read the complete "Critical Instructions for Claude" section
below ↓

---

## Critical Instructions for Claude

### 🎯 Context: What This Project Is

This is a **12-month solo developer project** in its **very early stages (Week
1-2 of 52)**. When working on this codebase, understand that:

1. **Current Reality:** Most components are NOT implemented yet. The project is
   still in foundation phase.
2. **Long-term Vision:** This will become a full autonomous AI platform with
   research integration.
3. **Incremental Development:** Focus on one phase at a time, don't try to build
   everything at once.

### 🚨 Critical Rules (ALWAYS FOLLOW)

#### 1. Never Break the Timeline

- **Current Phase:** Week 1-9 (Foundation)
- **DO NOT:** Jump ahead to Phase 3+ features
- **DO:** Focus on LangGraph orchestrator, package manager, research engine
  (Phase 1)
- **REASON:** Building advanced features before foundation = technical debt

#### 2. Always Use TypeScript Types

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

#### 3. Database Access Pattern

```typescript
// ✅ GOOD: Use pg client from packages/agent-core
import { createClient } from '@/packages/agent-core/src/clients/database';

// ❌ BAD: Direct psql queries or different clients
```

#### 4. Never Commit Secrets

- ❌ NO: API keys, passwords in code
- ✅ YES: Use `.env` files (already in `.gitignore`)
- ⚠️ VERIFY: Before any commit, check for secrets

#### 5. Test Everything (TDD Mandatory)

- **TDD Workflow:** ALWAYS write tests BEFORE implementation
  (Red-Green-Refactor)
- **Red-Green-Refactor Cycle:**
  1. 🔴 RED: Write failing test first
  2. 🟢 GREEN: Write minimal code to pass
  3. 🔵 REFACTOR: Improve code quality
- **No Exceptions:** No code without tests. Period.
- **Test Types Required:**
  - Unit: All pure functions, classes, utilities
  - Integration: Database, API, external service interactions
  - E2E: Critical user workflows only
- **Minimum Coverage:** 90%+ (enforced before commit)
- **Test Files:** `*.test.ts` (TypeScript), `*_test.py` (Python)
- **Pre-Commit Requirements:**
  - **Shortcut:** Run `pnpm run pre-commit` (runs all 4 checks below)
  - All tests passing (`pnpm test`)
  - Coverage ≥90% (`pnpm test:coverage`)
  - Linting passing (`pnpm lint`)
  - Type checking passing (`pnpm typecheck`)
  - No skipped/disabled tests without justification
- **See:** 🧪 Test-Driven Development (TDD) Guidelines section for complete
  details

#### 6. Follow Monorepo Structure

```
✅ GOOD: Place code in correct package
- Agent logic → packages/agent-core/
- Research → packages/research-engine/
- Code gen → packages/execution-engine/
- Python agents → services/python_agents/

❌ BAD: Create files in wrong locations or root
```

### 📝 Documentation Management Rules

**CRITICAL: This project uses EXACTLY THREE documentation files. No more, no
less.**

#### Files You CAN and MUST Update

| File          | Update Frequency     | What to Update                                                         |
| ------------- | -------------------- | ---------------------------------------------------------------------- |
| **CLAUDE.md** | Weekly               | Implementation status, metrics, timeline progress, environment changes |
| **STATUS.md** | Every 2-3 days       | Active work tracking, current goals, blockers, decisions               |
| **README.md** | Monthly or as needed | User-facing overview, setup instructions, getting started guide        |

#### What to Update in Each File

**CLAUDE.md** - Update these sections only:

- **Current Implementation Status** (Project Structure section) - Mark
  components as complete/in-progress
- **Current Status** in Project Overview - Update week number and phase
- **Success Metrics table** - Update "Current Status" column when you measure
  something
- **Environment Variables** - Add new variables when services are added
- **Key Files Reference** - Add important new files
- **Last Updated date** at bottom - Update to current date

**STATUS.md** - Update entire file as work progresses:

- Current week and phase
- This week's goals (checkboxes)
- Blockers encountered
- Decisions made
- Next week preview

**README.md** - Update as needed:

- Project description (rarely changes)
- Setup instructions (when new services added)
- Quick start guide (when workflow changes)
- Links to documentation

#### Strict Prohibitions - DO NOT:

❌ **NEVER create these files:**

- ARCHITECTURE.md
- DESIGN.md
- SPECS.md
- TECHNICAL_DETAILS.md
- API.md
- CONTRIBUTING.md
- CHANGELOG.md (we use git history)
- Any other .md files

❌ **NEVER modify these files:**

- `documentation_guide/FINAL_Autonomous_AI_Platform_Implementation_Guide.md`
  (original spec)
- `documentation_guide/Unified_Autonomous_Research_Platform_Architecture.md`
  (original spec)
- Any other files in `documentation_guide/` (these are frozen reference
  documents)

❌ **NEVER create documentation directories:**

- `/docs`
- `/documentation`
- `/wiki`
- `/guides`

#### Update Workflow

**When you complete a milestone:**

```bash
# 1. Update CLAUDE.md
# - Mark component status in "Current Implementation Status" table
# - Update success metrics if measured
# - Update "Last Updated" date
# - Update "Current Status" in Project Overview if week changed

# 2. Update STATUS.md
# - Check off completed goals
# - Add any new blockers
# - Document decisions made
# - Set next week's goals

# 3. Update README.md (only if needed)
# - Update setup instructions if infrastructure changed
# - Update quick start if workflow changed
```

#### Exception Handling

**If you think you need a new documentation file, STOP and:**

1. Ask yourself: "Can this go in CLAUDE.md?" (Answer: Yes, 99% of the time)
2. If architectural details: Add to CLAUDE.md Architecture section
3. If API documentation: Add to relevant code files as JSDoc comments
4. If still unsure: **Ask the user first** before creating any file

**Example of what to do:**

```
❌ Wrong: "I'll create an API.md file to document the endpoints"
✅ Right: "I'll add JSDoc comments to the endpoint functions and update
          the Architecture section in CLAUDE.md with API overview"

❌ Wrong: "I'll create a DECISIONS.md file to track architectural choices"
✅ Right: "I'll add decisions to STATUS.md under 'Decisions Made' section"

❌ Wrong: "I'll create a CHANGELOG.md to track changes"
✅ Right: "Git commit messages serve as our changelog. I'll update
          CLAUDE.md's 'Current Status' section with major milestones"
```

#### Rationale

**Why only 3 files?**

- **Focus:** Solo developer should code, not maintain documentation
- **Simplicity:** One source of truth (CLAUDE.md) for AI context
- **Overhead:** Multiple docs = stale docs = wrong information
- **Git History:** Commit messages already provide detailed changelog

**Remember:** Code and tests are the best documentation. Write clear code,
comprehensive tests, and JSDoc comments. Use CLAUDE.md, STATUS.md, and README.md
only for what can't be expressed in code.

### 📋 Code Style Guidelines

#### TypeScript

```typescript
// Use modern ES6+ syntax
import { ClaudeClient } from './clients/claude';

// Async/await over promises
async function fetchData(): Promise<Data> {
  const result = await client.query();
  return result;
}

// Explicit error handling
try {
  await riskyOperation();
} catch (error) {
  if (error instanceof ApiError) {
    // Handle specific error
  }
  throw error;
}
```

#### Python

```python
# Type hints required
def parse_paper(pdf_path: str) -> Paper:
    """Parse PDF and extract paper metadata."""
    pass

# Use dataclasses for structures
from dataclasses import dataclass

@dataclass
class Paper:
    title: str
    authors: list[str]
    abstract: str
```

#### Test Code

**TypeScript (Vitest) - AAA Pattern**

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ✅ GOOD: Descriptive names, AAA pattern, proper mocking
describe('ClaudeClient', () => {
  let client: ClaudeClient;

  beforeEach(() => {
    // Fresh instance for each test
    client = new ClaudeClient();
  });

  it('should send message and receive response from Claude API', async () => {
    // ARRANGE
    const messages = [{ role: 'user', content: 'Hello' }];
    const expectedResponse = { content: [{ text: 'Hi there!' }] };
    vi.spyOn(client['client'].messages, 'create').mockResolvedValue(
      expectedResponse
    );

    // ACT
    const response = await client.chat(messages);

    // ASSERT
    expect(response.content[0].text).toBe('Hi there!');
  });

  it('should throw ApiError when network request fails', async () => {
    // ARRANGE
    vi.spyOn(client['client'].messages, 'create').mockRejectedValue(
      new Error('Network timeout')
    );

    // ACT & ASSERT
    await expect(
      client.chat([{ role: 'user', content: 'Test' }])
    ).rejects.toThrow('Network timeout');
  });
});

// ❌ BAD: Vague names, no structure, hard to understand
test('client works', async () => {
  const c = new ClaudeClient();
  const r = await c.chat([{ role: 'user', content: 'hi' }]);
  expect(r).toBeDefined();
});
```

**Python (pytest) - Given-When-Then Pattern**

```python
import pytest
from unittest.mock import Mock, patch

# ✅ GOOD: Fixtures, descriptive names, Given-When-Then structure
class TestPaperParser:
    @pytest.fixture
    def parser(self):
        """Provide fresh parser for each test."""
        return PaperParser()

    @pytest.fixture
    def valid_pdf(self, tmp_path):
        """Provide a valid PDF file."""
        pdf = tmp_path / "paper.pdf"
        pdf.write_bytes(SAMPLE_PDF_BYTES)
        return pdf

    def test_should_extract_title_when_pdf_is_valid(self, parser, valid_pdf):
        """
        GIVEN a valid PDF with title metadata
        WHEN parsing the PDF
        THEN should return paper with extracted title
        """
        # WHEN
        paper = parser.parse(valid_pdf)

        # THEN
        assert paper.title == "Expected Title"
        assert paper.authors == ["Author One", "Author Two"]

    def test_should_raise_parse_error_when_pdf_is_corrupted(self, parser, tmp_path):
        """
        GIVEN a corrupted PDF file
        WHEN attempting to parse
        THEN should raise ParseError
        """
        # GIVEN
        corrupt_pdf = tmp_path / "corrupt.pdf"
        corrupt_pdf.write_bytes(b"invalid")

        # WHEN & THEN
        with pytest.raises(ParseError) as exc:
            parser.parse(corrupt_pdf)
        assert "corrupted" in str(exc.value).lower()

# ❌ BAD: No structure, unclear expectations
def test_parser():
    p = PaperParser()
    result = p.parse("file.pdf")
    assert result
```

### 🔒 Security Considerations

#### Never Do:

1. **SQL Injection:** Always use parameterized queries
2. **XSS:** Always sanitize user input
3. **Command Injection:** Never use `exec()` with user input
4. **Path Traversal:** Validate all file paths
5. **Secrets in Code:** Use environment variables

#### Always Do:

1. **Input Validation:** Validate all user inputs
2. **Output Encoding:** Encode all outputs
3. **Least Privilege:** Containers run as non-root
4. **Secure Defaults:** Fail securely
5. **Audit Trail:** Log security events

### 🎨 Architecture Patterns to Follow

#### 1. Orchestrator Pattern (LangGraph)

```python
# Use LangGraph for agent orchestration
from langgraph.graph import StateGraph

graph = StateGraph(AgentState)
graph.add_node("intent_parser", parse_intent)
graph.add_node("task_planner", plan_task)
graph.add_edge("intent_parser", "task_planner")
```

#### 2. Repository Pattern (Database Access)

```typescript
// Use repository pattern for data access
class PackageRepository {
  async findByName(name: string): Promise<Package | null> {
    // Implementation
  }
}
```

#### 3. Strategy Pattern (Algorithm Selection)

```typescript
// Use strategy pattern for different algorithms
interface OptimizationStrategy {
  optimize(code: string): OptimizedCode;
}

class HyperLogLogStrategy implements OptimizationStrategy {
  // Implementation
}
```

### 📊 When Making Changes

#### Before Any Code Change, Ask:

1. **Is this in the current phase?** (Check timeline section)
2. **Does this require new dependencies?** (Document in package.json)
3. **Is this tested?** (Write tests first/alongside)
4. **Does this follow types?** (No `any` types)
5. **Is this documented?** (Add JSDoc comments)

#### Commit Message Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** feat, fix, docs, style, refactor, test, chore

**Example:**

```
feat(agent-core): implement LangGraph orchestrator

- Add state machine with intent parser and task planner nodes
- Integrate Claude Sonnet 4.5 API
- Add error recovery using Reflexion pattern

Addresses Phase 1, Week 3-4 milestone
```

**Before Committing:** Always run `pnpm run pre-commit` to ensure all checks
pass (typecheck, lint, test, coverage).

**CRITICAL - Lockfile Regeneration:** If you updated any package versions in
`package.json` files (e.g., `@types/node: ^24.9.2` → `^24.10.0`), you MUST
regenerate the lockfile before committing:

```bash
# After updating package.json versions, run:
pnpm install

# This updates pnpm-lock.yaml with new versions
# Then commit both package.json AND pnpm-lock.yaml together
```

**Why:** CI uses `--frozen-lockfile` which fails if lockfile doesn't match
package.json. This prevents deployment failures and ensures reproducible builds.

#### Commit Strategy: When and How to Commit

**CRITICAL: Understanding when to commit and how to handle multiple file changes
is essential for maintaining a clean git history.**

##### When to Commit

**Commit Frequency Guidelines:**

- ✅ **DO commit** after completing a logical unit of work (feature, fix,
  refactor)
- ✅ **DO commit** after TDD cycle completes (Red-Green-Refactor)
- ✅ **DO commit** when all tests pass and coverage is ≥90%
- ✅ **DO commit** before switching to a different task
- ❌ **DON'T commit** incomplete features (use feature branches if needed)
- ❌ **DON'T commit** broken code (unless explicitly WIP with clear message)
- ❌ **DON'T batch** unrelated changes into one commit

**Golden Rule:** One logical change = one commit. If you can't describe the
commit in one sentence, it should probably be split.

##### Multiple Files, Different Types: Decision Framework

When you've changed multiple files that could classify as different commit
types, use this decision framework:

**Approach 1: Multiple Atomic Commits (✅ RECOMMENDED)**

Split changes into separate, logical commits - one per type/scope.

```bash
# Scenario: You fixed a bug AND added a new feature

# Commit 1: Bug fix
git add packages/agent-core/src/parser.ts
git commit -m "fix(agent-core): resolve intent parsing null error

- Add null check in parseIntent function
- Handle edge case for empty user input

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Commit 2: New feature
git add packages/research-engine/src/arxiv-monitor.ts \
        packages/research-engine/src/arxiv-monitor.test.ts
git commit -m "feat(research): add daily arXiv paper monitoring

- Implement daily cron job for arXiv API
- Add comprehensive test coverage (TDD)
- Include retry logic for network failures

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Commit 3: Update docs
git add CLAUDE.md STATUS.md
git commit -m "docs: document new arXiv monitoring feature

- Update CLAUDE.md with monitoring architecture
- Update STATUS.md with Week 2 progress

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Benefits:**

- ✅ Clear, focused git history
- ✅ Easy to revert specific changes
- ✅ Better code review experience
- ✅ Clean changelogs

**Approach 2: Choose the Dominant Type**

When changes are tightly coupled, pick the most significant change type.

```bash
# Feature that requires test updates and doc updates

git add packages/agent-core/src/orchestrator.ts \
        packages/agent-core/src/orchestrator.test.ts \
        CLAUDE.md

git commit -m "feat(agent-core): implement LangGraph orchestrator

- Add state machine with intent parser and task planner nodes
- Add comprehensive test coverage (100%, TDD)
- Update CLAUDE.md with architecture details

Addresses Phase 1, Week 3-4 milestone

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**When to use:**

- Feature + its tests → `feat`
- Bug fix + its tests → `fix`
- Refactor + updated docs → `refactor`

**Approach 3: Use Broader Scope**

For changes spanning multiple packages, use a parent scope or omit scope.

```bash
# Changes across multiple packages

# Option A: No scope (project-wide changes)
git commit -m "chore: upgrade all dependencies to latest versions

- Update package.json for all workspaces
- Run pnpm update across monorepo
- Verify all tests still pass

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Option B: Use "repo" scope
git commit -m "chore(repo): add pre-commit hooks and CI workflow

- Add Husky for git hooks
- Add lint-staged for automated checks
- Add GitHub Actions CI workflow

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

# Option C: Multiple scopes (if commitlint allows)
git commit -m "feat(agent-core,research): integrate paper search with orchestrator

- Connect research engine to main orchestrator
- Add cross-package integration tests
- Update both packages' APIs

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Approach 4: The "Chore" Escape Hatch**

For tooling/infrastructure changes affecting everything, use `chore`.

```bash
# Update ESLint, format all files, update CI

git commit -m "chore(tooling): add ESLint and Prettier with auto-formatting

- Add ESLint config with TypeScript support
- Add Prettier config with project standards
- Format all existing files (no logic changes)
- Update CI to run linting checks
- Add pre-commit hooks for automated formatting

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

##### Decision Tree

```
Do the changes belong together logically?
├─ YES: Single commit with dominant type
│   └─ What's the main purpose?
│       ├─ Adding capability → feat
│       ├─ Fixing bug → fix
│       ├─ Docs/tests supporting above → Use that type
│       └─ Tooling/config → chore
│
└─ NO: Multiple commits
    └─ Split by:
        ├─ Type (feat vs fix vs docs)
        ├─ Scope (different packages)
        └─ Feature (different user-facing changes)
```

##### Real Examples from Your Project

**Example 1: Today's Work (Multiple Separate Commits)**

We made multiple separate commits:

```bash
# Commit 1: Tooling setup
"chore: add pre-commit hooks and Python tooling"

# Commit 2: Fix Husky deprecation
"fix(husky): remove deprecated hook format for v10 compatibility"

# Commit 3: Fix CI Python job
"fix(ci): resolve Python mypy and Docker security scan issues"

# Commit 4: New security feature
"feat(ci): implement comprehensive Docker security scan with Trivy"
```

**Why separate?** Each addresses a different concern and could be reverted
independently.

**Example 2: Feature + Tests + Docs (Single Commit)**

```bash
git add packages/agent-core/src/clients/claude-client.ts \
        packages/agent-core/src/clients/claude-client.test.ts \
        CLAUDE.md

git commit -m "feat(agent-core): add streaming chat support to ClaudeClient

- Implement streamChat() method with onChunk callback
- Add comprehensive test coverage (100%, TDD)
- Update CLAUDE.md with usage examples

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**Why single commit?** Tests and docs directly support the feature.

**Example 3: Multi-Package Feature (Broader Scope)**

```bash
# Changes span agent-core, research-engine, and execution-engine

git commit -m "feat: implement end-to-end paper-to-code pipeline

- agent-core: Add paper analysis coordinator
- research-engine: Extract algorithms from PDFs
- execution-engine: Generate TypeScript from algorithms
- Add integration tests across packages
- Update architecture documentation

Addresses Phase 1, Week 7-8 milestone

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

**No scope** because it spans multiple packages for one user-facing feature.

##### TDD Commit Patterns

**Pattern 1: Separate Commits (Recommended for Learning)**

```bash
# 1. RED: Write failing test
git add packages/agent-core/src/parser.test.ts
git commit -m "test(agent-core): add test for package intent detection"

# 2. GREEN: Implement feature
git add packages/agent-core/src/parser.ts
git commit -m "feat(agent-core): implement package intent detection"

# 3. REFACTOR: Clean up
git add packages/agent-core/src/parser.ts
git commit -m "refactor(agent-core): simplify intent detection logic"
```

**Pattern 2: Combined (More Common in Practice)**

```bash
# RED-GREEN-REFACTOR in one commit
git add packages/agent-core/src/parser.ts \
        packages/agent-core/src/parser.test.ts

git commit -m "feat(agent-core): implement package intent detection

- Add parseIntent() function with regex matching
- Add comprehensive test coverage (TDD: Red-Green-Refactor)
- Handle edge cases: null, empty, malformed input

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

##### Practical Workflow with git add -p

Use selective staging to separate unrelated changes:

```bash
# You changed 10 files across 3 types of work

# Stage only the bug fix
git add packages/agent-core/src/parser.ts
git commit -m "fix(agent-core): handle null intent gracefully"

# Stage the new feature
git add packages/research-engine/src/monitor.ts \
        packages/research-engine/src/monitor.test.ts
git commit -m "feat(research): add arXiv monitoring"

# Stage the docs
git add CLAUDE.md README.md
git commit -m "docs: update architecture and setup guide"

# OR use interactive staging
git add -p  # Pick hunks interactively
```

##### Quick Reference Table

| Scenario                 | Approach         | Example                                        |
| ------------------------ | ---------------- | ---------------------------------------------- |
| Feature + its tests      | Single `feat`    | `feat(agent): add streaming with tests`        |
| Bug fix + its tests      | Single `fix`     | `fix(api): resolve timeout with test coverage` |
| Multiple unrelated fixes | Multiple commits | Separate `fix` commits                         |
| Multi-package feature    | Single, no scope | `feat: implement end-to-end pipeline`          |
| Tooling across repo      | Single `chore`   | `chore: add linting and formatting`            |
| Docs + code changes      | Dominant type    | Use `feat`/`fix`, mention docs in body         |

**Golden Rule:** When in doubt, **split into multiple commits**. It's easier to
squash later than to split apart!

##### Commit Checklist

Before committing, ask yourself:

1. ✅ **Is this a logical unit of work?** (Can describe in one sentence)
2. ✅ **Do all tests pass?** (`pnpm test`)
3. ✅ **Is coverage ≥90%?** (`pnpm test:coverage`)
4. ✅ **Does linting pass?** (`pnpm lint`)
5. ✅ **Do types check?** (`pnpm typecheck`)
6. ✅ **Is commit message descriptive?** (Follows conventional commits)
7. ✅ **Are unrelated changes separated?** (Use `git add -p` if needed)
8. ✅ **No secrets committed?** (Check .env, API keys)

**Shortcut:** Run `pnpm run pre-commit` to check items 2-5 automatically.

### 🐛 Debugging Guidelines

#### When Encountering Errors:

1. **Check Logs:** Always log errors with context
2. **Verify Services:** Ensure Docker services are running
3. **Check Environment:** Verify `.env` file
4. **Test Isolation:** Reproduce in sandbox
5. **Ask User:** If unclear, ask before proceeding

#### Logging Pattern

```typescript
import { logger } from '@/lib/logger';

logger.info('Starting task execution', { taskId, userId });
logger.error('Task execution failed', { error, taskId });
```

### 📚 Documentation Requirements

#### Always Document:

1. **Functions:** JSDoc comments for all public functions
2. **Types:** Description for all interfaces
3. **Decisions:** Why you chose an approach
4. **TODO:** Mark incomplete areas with TODO comments

```typescript
/**
 * Generates TypeScript code from research paper algorithm.
 *
 * @param algorithm - Extracted algorithm from paper
 * @param context - Code generation context
 * @returns Generated TypeScript code with imports
 * @throws {GenerationError} If algorithm cannot be converted
 */
async function generateCode(
  algorithm: Algorithm,
  context: GenerationContext
): Promise<GeneratedCode> {
  // TODO: Add support for Python code generation (Phase 2)
  // Implementation...
}
```

### ⚡ Performance Guidelines

#### DO:

- Cache Claude API responses (90% cost reduction target)
- Use indexes on database queries
- Batch operations when possible
- Profile before optimizing

#### DON'T:

- Make multiple API calls when one suffices
- Load entire datasets into memory
- Optimize without measuring first

### 🤝 User Interaction

#### When User Asks for:

1. **New Feature:** Check if it's in current phase
   - If yes → Implement
   - If no → Explain timeline, offer alternative

2. **Bug Fix:** Always prioritize
   - Fix immediately
   - Add test to prevent regression

3. **Unclear Request:** Ask clarifying questions
   - Don't guess
   - Provide options

4. **Optimization:** Measure first
   - Profile current performance
   - Compare before/after

### 🎯 Success Criteria Checklist

Before marking any task complete, verify:

**Code Quality:**

- [ ] Code compiles/runs without errors
- [ ] Types are explicit (no `any`)
- [ ] Documentation added (JSDoc comments)
- [ ] Follows project structure
- [ ] No secrets committed

**Testing (TDD Required):**

- [ ] Tests written FIRST (TDD: Red-Green-Refactor cycle followed)
- [ ] All tests passing (90%+ coverage verified)
- [ ] Unit tests for all functions/classes/utilities
- [ ] Integration tests for database/API/external service interactions
- [ ] E2E tests for critical user workflows (if applicable)
- [ ] Edge cases and error conditions tested
- [ ] Mocks/stubs used appropriately (no real external API calls in tests)
- [ ] Test names are descriptive and follow conventions
- [ ] Test data properly managed (factories/fixtures used)

**Security & Performance:**

- [ ] Security checked (no vulnerabilities)
- [ ] Performance acceptable (<2s P99 latency)

**Version Control:**

- [ ] Git commit message follows format

### 🔄 Self-Check Questions

Before every response to user, ask yourself:

**Phase & Architecture:**

1. Am I working on the right phase? (Currently: Phase 1)
2. Did I follow TypeScript/Python style guidelines?
3. Does this follow the project structure?

**Testing (TDD):** 4. Did I write tests FIRST before implementation?
(Red-Green-Refactor) 5. Did I write unit tests for all new functions/classes? 6.
Did I write integration tests for database/API interactions? 7. Are all tests
passing with 90%+ coverage? 8. Did I test edge cases and error conditions? 9.
Did I use proper mocking for external services? 10. Are test names descriptive
and follow conventions?

**Quality & Security:** 11. Did I check for security issues? 12. Did I document
my changes (JSDoc comments)? 13. Did I verify nothing breaks (all existing tests
still pass)? 14. Are types explicit (no `any`)?

**Performance:** 15. Is performance acceptable (<2s P99 latency)? 16. Did I
profile if making performance changes?

### 📞 When to Ask User

**Always ask user when:**

- Requirements are ambiguous
- Multiple valid approaches exist
- About to make breaking changes
- Need to deviate from timeline
- Encountering unexpected errors
- Need additional API keys/credentials

**Example:**

```
"I notice you're asking for feature X, which is planned for Phase 3
(Week 20). Would you like me to:
1. Implement a simplified version now for Phase 1
2. Wait until Phase 3 as planned
3. Adjust the timeline to prioritize this feature"
```

### 🧪 Test-Driven Development (TDD) Guidelines

**CRITICAL: Test-Driven Development is MANDATORY for all code in this project.**

#### TDD Workflow (Red-Green-Refactor)

Every single feature, function, or class MUST follow this cycle:

```
1. 🔴 RED: Write a failing test first
   - Write the test for functionality that doesn't exist yet
   - Run test → verify it fails (red)
   - This proves the test is actually testing something

2. 🟢 GREEN: Write minimal code to pass the test
   - Write the simplest code that makes the test pass
   - Don't worry about perfection yet
   - Run test → verify it passes (green)

3. 🔵 REFACTOR: Improve the code quality
   - Clean up the code
   - Remove duplication
   - Improve naming and structure
   - Run tests → verify still passing

4. ♻️ REPEAT: For each new requirement
```

**Example TDD Workflow:**

```typescript
// Step 1: RED - Write failing test
describe('parseIntent', () => {
  it('should identify package installation intent', () => {
    const result = parseIntent('Install lodash');
    expect(result.type).toBe('INSTALL_PACKAGE');
    expect(result.packageName).toBe('lodash');
  });
});
// Run test → FAILS (parseIntent doesn't exist yet) ✓

// Step 2: GREEN - Minimal implementation
export function parseIntent(input: string) {
  if (input.toLowerCase().includes('install')) {
    const packageName = input.split(' ')[1];
    return { type: 'INSTALL_PACKAGE', packageName };
  }
  return { type: 'UNKNOWN', packageName: null };
}
// Run test → PASSES ✓

// Step 3: REFACTOR - Improve code quality
export function parseIntent(input: string): Intent {
  const normalizedInput = input.toLowerCase().trim();
  const words = normalizedInput.split(/\s+/);

  if (words[0] === 'install' && words[1]) {
    return {
      type: IntentType.INSTALL_PACKAGE,
      packageName: words[1],
    };
  }

  return {
    type: IntentType.UNKNOWN,
    packageName: null,
  };
}
// Run test → STILL PASSES ✓

// Step 4: REPEAT - Add edge case tests and implement
it('should handle install command with extra spaces', () => {
  const result = parseIntent('  install   lodash  ');
  expect(result.type).toBe('INSTALL_PACKAGE');
  expect(result.packageName).toBe('lodash');
});
```

#### Test Type Decision Matrix

**Use this table to decide which type of test to write:**

| What You're Testing     | Test Type     | Framework          | Speed  | Example                                  |
| ----------------------- | ------------- | ------------------ | ------ | ---------------------------------------- |
| Pure function (no I/O)  | Unit          | Vitest/pytest      | <100ms | `parseIntent()`, `calculateComplexity()` |
| Class/module (isolated) | Unit          | Vitest/pytest      | <100ms | `ClaudeClient` (mocked), `IntentParser`  |
| Utility functions       | Unit          | Vitest/pytest      | <100ms | `formatDate()`, `validateEmail()`        |
| Database query          | Integration   | Testcontainers     | 1-5s   | `PackageRepo.findByName()`               |
| Redis caching           | Integration   | Testcontainers     | 1-5s   | `CacheService.get()`                     |
| API endpoint            | Integration   | Vitest + Supertest | 1-5s   | `POST /api/tasks`                        |
| External API call       | Unit (mocked) | Vitest + vi.mock() | <100ms | `anthropic.messages.create()`            |
| File system operations  | Integration   | Vitest + tmp       | <1s    | `PdfParser.parse()`                      |
| Complete user workflow  | E2E           | Playwright         | 10-60s | "Create task → Execute → View results"   |

**Decision Rules:**

- If it has **NO external dependencies** → Unit test (fast, isolated)
- If it touches **database/cache/filesystem** → Integration test (slower, real
  dependencies)
- If it's a **critical user journey** → E2E test (slowest, end-to-end)

#### Test Structure Patterns

**AAA Pattern (Arrange-Act-Assert) - TypeScript**

```typescript
import { describe, it, expect, beforeEach } from 'vitest';

describe('PackageRepository', () => {
  let repo: PackageRepository;
  let mockDb: Database;

  beforeEach(() => {
    // Setup fresh state for each test
    mockDb = createMockDatabase();
    repo = new PackageRepository(mockDb);
  });

  it('should return package when found by exact name', async () => {
    // ✅ ARRANGE: Set up test data
    const expectedPackage = {
      id: '123',
      name: 'lodash',
      version: '4.17.21',
      ecosystem: 'npm',
    };
    await mockDb.packages.insert(expectedPackage);

    // ✅ ACT: Execute the function under test
    const result = await repo.findByName('lodash');

    // ✅ ASSERT: Verify the outcome
    expect(result).toEqual(expectedPackage);
  });

  it('should return null when package not found', async () => {
    // ARRANGE: Empty database (no setup needed)

    // ACT
    const result = await repo.findByName('nonexistent');

    // ASSERT
    expect(result).toBeNull();
  });

  it('should throw DatabaseError when connection fails', async () => {
    // ARRANGE
    mockDb.simulateConnectionFailure();

    // ACT & ASSERT combined for exceptions
    await expect(repo.findByName('lodash')).rejects.toThrow(DatabaseError);
    await expect(repo.findByName('lodash')).rejects.toThrow('Connection lost');
  });
});
```

**Given-When-Then Pattern - Python (pytest)**

```python
import pytest
from unittest.mock import Mock, patch

class TestPaperParser:
    """Test suite for PDF paper parsing functionality."""

    @pytest.fixture
    def parser(self):
        """Provide a fresh parser instance for each test."""
        return PaperParser()

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """Provide a sample PDF file for testing."""
        pdf_file = tmp_path / "sample_paper.pdf"
        pdf_file.write_bytes(VALID_PDF_CONTENT)
        return pdf_file

    def test_should_extract_title_from_valid_pdf(self, parser, sample_pdf):
        """
        GIVEN a valid PDF with title in metadata
        WHEN parsing the PDF
        THEN should extract the title correctly
        """
        # GIVEN - fixtures provide the setup

        # WHEN
        paper = parser.parse(sample_pdf)

        # THEN
        assert paper.title == "Sample Research Paper"
        assert paper.title is not None
        assert len(paper.title) > 0

    def test_should_raise_error_when_pdf_is_corrupted(self, parser, tmp_path):
        """
        GIVEN a corrupted PDF file
        WHEN attempting to parse
        THEN should raise ParseError with descriptive message
        """
        # GIVEN
        corrupted_pdf = tmp_path / "corrupted.pdf"
        corrupted_pdf.write_bytes(b"not a valid pdf")

        # WHEN & THEN
        with pytest.raises(ParseError) as exc_info:
            parser.parse(corrupted_pdf)

        assert "corrupted" in str(exc_info.value).lower()
```

**Descriptive Test Naming Conventions:**

```typescript
// ❌ BAD: Vague, non-descriptive names
test('works');
test('package test');
test('should work correctly');

// ✅ GOOD: Describes what, when, and expected outcome
it('should return 404 when package not found in database');
it('should parse install intent from "install lodash" command');
it('should throw ApiError when network request times out');
it('should cache result for 5 minutes after successful fetch');
it('should retry 3 times before failing on network errors');

// Pattern: should [expected behavior] when [condition]
```

#### Mocking & Stubbing External Dependencies

**Mocking Anthropic API Calls (Vitest)**

```typescript
import { vi } from 'vitest';
import { ClaudeClient } from './claude-client';

// Mock the entire module
vi.mock('@anthropic-ai/sdk', () => ({
  Anthropic: vi.fn().mockImplementation(() => ({
    messages: {
      create: vi.fn().mockResolvedValue({
        content: [{ type: 'text', text: 'Mocked response' }],
        usage: { input_tokens: 10, output_tokens: 20 },
      }),
    },
  })),
}));

describe('ClaudeClient', () => {
  it('should send message and return response', async () => {
    // ARRANGE
    const client = new ClaudeClient();

    // ACT
    const response = await client.chat([
      { role: 'user', content: 'Test message' },
    ]);

    // ASSERT
    expect(response.content[0].text).toBe('Mocked response');
  });
});
```

**Mocking Database with Spies (Vitest)**

```typescript
import { vi } from 'vitest';

describe('PackageService', () => {
  it('should call repository findByName method', async () => {
    // ARRANGE
    const mockRepo = {
      findByName: vi.fn().mockResolvedValue({ name: 'lodash' }),
    };
    const service = new PackageService(mockRepo);

    // ACT
    await service.getPackage('lodash');

    // ASSERT
    expect(mockRepo.findByName).toHaveBeenCalledWith('lodash');
    expect(mockRepo.findByName).toHaveBeenCalledTimes(1);
  });
});
```

**Mocking with pytest (Python)**

```python
from unittest.mock import Mock, patch, MagicMock

def test_should_call_arxiv_api_with_correct_parameters():
    """GIVEN a paper ID, WHEN fetching from arXiv, THEN should call API correctly."""
    # ARRANGE
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'title': 'Test Paper'}

    with patch('requests.get', return_value=mock_response) as mock_get:
        fetcher = ArxivFetcher()

        # ACT
        paper = fetcher.fetch('2301.12345')

        # ASSERT
        mock_get.assert_called_once_with(
            'https://export.arxiv.org/api/query',
            params={'id_list': '2301.12345'}
        )
        assert paper['title'] == 'Test Paper'
```

#### Test Data Management

**Factory Functions (TypeScript)**

```typescript
// test/factories/package.factory.ts
import { randomUUID } from 'crypto';

export function createMockPackage(overrides: Partial<Package> = {}): Package {
  return {
    id: randomUUID(),
    name: 'test-package',
    version: '1.0.0',
    ecosystem: 'npm',
    description: 'Test package description',
    downloads_last_month: 1000,
    github_stars: 100,
    created_at: new Date(),
    ...overrides, // Allow customization
  };
}

// Usage in tests
it('should save package to database', async () => {
  const package = createMockPackage({ name: 'lodash', version: '4.17.21' });
  await repo.save(package);

  const found = await repo.findByName('lodash');
  expect(found.version).toBe('4.17.21');
});
```

**Fixtures (pytest)**

```python
# tests/fixtures.py
import pytest
from datetime import datetime

@pytest.fixture
def sample_paper():
    """Provide a sample research paper for testing."""
    return Paper(
        id='123',
        arxiv_id='2301.12345',
        title='Test Paper',
        authors=['Author One', 'Author Two'],
        abstract='This is a test abstract',
        published_date=datetime(2023, 1, 15)
    )

@pytest.fixture
def empty_database(db_session):
    """Provide a clean database for each test."""
    db_session.query(Paper).delete()
    db_session.commit()
    yield db_session
    db_session.rollback()

# Usage in tests
def test_should_store_paper_in_database(empty_database, sample_paper):
    empty_database.add(sample_paper)
    empty_database.commit()

    found = empty_database.query(Paper).filter_by(arxiv_id='2301.12345').first()
    assert found.title == 'Test Paper'
```

#### Edge Cases and Error Conditions

**Always test these scenarios:**

```typescript
describe('Edge Cases and Errors', () => {
  // Null/undefined inputs
  it('should handle null input gracefully', () => {
    expect(() => parseIntent(null)).toThrow(ValidationError);
  });

  it('should handle undefined input gracefully', () => {
    expect(() => parseIntent(undefined)).toThrow(ValidationError);
  });

  // Empty inputs
  it('should handle empty string', () => {
    const result = parseIntent('');
    expect(result.type).toBe('UNKNOWN');
  });

  // Boundary conditions
  it('should handle maximum length input', () => {
    const longInput = 'a'.repeat(10000);
    expect(() => parseIntent(longInput)).not.toThrow();
  });

  // Invalid formats
  it('should handle malformed JSON gracefully', () => {
    expect(() => JSON.parse('invalid')).toThrow(SyntaxError);
  });

  // Network errors
  it('should retry on network timeout', async () => {
    const mockFetch = vi
      .fn()
      .mockRejectedValueOnce(new Error('ETIMEDOUT'))
      .mockRejectedValueOnce(new Error('ETIMEDOUT'))
      .mockResolvedValueOnce({ data: 'success' });

    const result = await fetchWithRetry(mockFetch);
    expect(result.data).toBe('success');
    expect(mockFetch).toHaveBeenCalledTimes(3);
  });

  // Permission errors
  it('should throw PermissionError when unauthorized', async () => {
    await expect(deletePackage('lodash')).rejects.toThrow(PermissionError);
  });
});
```

#### Integration Test Setup with Testcontainers

**PostgreSQL Integration Tests**

```typescript
// packages/agent-core/src/repositories/package.integration.test.ts
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import {
  PostgreSqlContainer,
  StartedPostgreSqlContainer,
} from '@testcontainers/postgresql';
import { Client } from 'pg';

let container: StartedPostgreSqlContainer;
let client: Client;

beforeAll(async () => {
  // Start PostgreSQL container
  container = await new PostgreSqlContainer('pgvector/pgvector:pg15')
    .withDatabase('test_db')
    .withUsername('test')
    .withPassword('test')
    .start();

  // Connect and run migrations
  client = new Client({
    host: container.getHost(),
    port: container.getPort(),
    database: container.getDatabase(),
    user: container.getUsername(),
    password: container.getPassword(),
  });

  await client.connect();
  await runMigrations(client);
}, 60000); // 60s timeout for container start

afterAll(async () => {
  await client.end();
  await container.stop();
});

describe('PackageRepository Integration Tests', () => {
  it('should insert and retrieve package from real database', async () => {
    // ARRANGE
    const repo = new PackageRepository(client);
    const package = {
      name: 'lodash',
      version: '4.17.21',
      ecosystem: 'npm',
    };

    // ACT
    await repo.save(package);
    const found = await repo.findByName('lodash');

    // ASSERT
    expect(found).toBeDefined();
    expect(found.name).toBe('lodash');
    expect(found.version).toBe('4.17.21');
  });
});
```

#### Pre-Commit Testing Requirements

**Before EVERY commit, you MUST:**

```bash
# Shortcut: Run all 4 checks at once
pnpm run pre-commit

# OR run individually:
# 1. Run all tests
pnpm test

# 2. Verify coverage meets 90%+ threshold
pnpm test:coverage

# 3. Run linter
pnpm lint

# 4. Type check
pnpm typecheck
```

**What `pnpm run pre-commit` does:**

- Runs `pnpm typecheck` → TypeScript type validation
- Runs `pnpm lint` → ESLint code quality checks
- Runs `pnpm test` → All unit/integration tests
- Runs `pnpm test:coverage` → Enforces 90%+ coverage threshold

**All checks MUST pass before committing code.**

**Continuous Testing During Development:**

```bash
# Watch mode - auto-run tests on file changes
pnpm test:watch

# Watch specific file
pnpm test:watch packages/agent-core/src/parser.test.ts
```

#### Summary: TDD Checklist for Every Feature

Before marking any task complete, verify:

- [ ] **RED:** Wrote failing test first
- [ ] **GREEN:** Implemented minimal code to pass
- [ ] **REFACTOR:** Cleaned up code while keeping tests green
- [ ] **Unit tests:** All functions/classes have unit tests
- [ ] **Integration tests:** Database/API interactions tested
- [ ] **Edge cases:** Null, empty, boundary conditions tested
- [ ] **Error conditions:** All error paths tested
- [ ] **Mocks:** External dependencies properly mocked
- [ ] **Coverage:** ≥90% test coverage achieved
- [ ] **Descriptive names:** Test names clearly describe behavior
- [ ] **AAA pattern:** Tests follow Arrange-Act-Assert structure
- [ ] **Tests passing:** All tests green before commit

**Remember: No code without tests. No exceptions.**

---

## Project Changelog

### 2025-11-08 (Week 2) - Configuration Files Enhanced

**Comprehensive Configuration Overhaul**

- ✅ Enhanced 11+ configuration files with industry best practices
  - package.json: Added metadata (description, keywords, author, repository,
    engines)
  - commitlint.config.ts: Added 4 new commit types (perf, ci, build, revert) +
    line length rules
  - .gitignore: Added 9 new patterns (.env.vault, .husky/\_, .yarn/, .turbo/,
    macOS files, junit.xml)
  - renovate.json: Enhanced with automerge, security alerts, package grouping
  - .dockerignore: Added 8 new patterns for dev configs and OS files
  - .prettierignore: Added 15+ new patterns for comprehensive coverage

**Cross-Platform Compatibility**

- ✅ Created .gitattributes file (NEW)
  - LF line-ending enforcement for all text files
  - Explicit declarations for source files (_.ts, _.js, _.py, _.json, \*.sh)
  - Binary file declarations (_.png, _.jpg, _.pdf, _.zip, _.woff, _.ttf)

**CI/CD Integration**

- ✅ Enhanced vitest.config.ts
  - Added JUnit XML reporter for CI environments (conditional on process.env.CI)
  - Output file: ./coverage/junit.xml
  - Enables structured test reporting in GitHub Actions, Jenkins, etc.

**Code Quality Improvements**

- ✅ Fixed eslint.config.js
  - Removed broad _.config._ ignore pattern
  - Enabled linting for package-level config files
  - Selective ignores for root-level tooling configs only

**TypeScript Project Fixes**

- ✅ Created placeholder packages to resolve TypeScript configuration errors
  - packages/research-engine/src/index.ts (placeholder for Phase 1, Week 7-8)
  - packages/execution-engine/src/index.ts (placeholder for Phase 2, Week 10-14)
  - Fixed ESLint parsing errors for empty packages

**Git Workflow**

- ✅ Merged all enhancements to master branch
  - Commit 740b86f: First batch (metadata, ignores, automation)
  - Commit aa915bd: Second batch (gitattributes, CI, placeholders)
  - PR #2: Merged 740b86f via commit aede797
  - PR #3: Merged aa915bd via commit 509041e
  - All enhancements verified intact on master branch

**Decisions Made:**

1. **Git Line Endings** - Enforce LF (Unix) line endings across all platforms
   via .gitattributes
2. **CI Reporting** - Use JUnit XML format for test reports in CI pipelines
3. **Config File Linting** - Enable ESLint for package-level configs while
   excluding root tooling configs
4. **Dependency Automation** - Automerge patch updates and prioritize security
   vulnerabilities in Renovate

**Impact:** Infrastructure tooling now follows enterprise-grade best practices,
improving code quality, CI/CD integration, and developer onboarding experience.

---

### 2025-11-01 (Week 2)

**Documentation System Established**

- ✅ Created CLAUDE.md (1,100+ lines) - Comprehensive technical documentation
  - 10 major sections covering all aspects of the platform
  - Critical instructions for Claude with strict guidelines
  - Documentation management rules (3-file system)
- ✅ Created STATUS.md - Weekly progress tracking
  - Current sprint goals and completion status
  - Decisions log and blockers tracking
  - Next week preview with success criteria
- ✅ Created README.md - User-facing project overview
  - Quick start guide and installation instructions
  - Architecture overview and roadmap
  - Troubleshooting section

**Infrastructure Complete**

- ✅ Docker environment configured
  - PostgreSQL 16 + pgvector extension (port 5432)
  - Redis 7.x (port 6379)
  - Qdrant vector database (port 6333)
- ✅ Database schema designed (6 tables)
  - packages, research_papers, generated_code
  - task_executions, performance_metrics, user_feedback
  - pgvector integration for semantic search
- ✅ Monorepo structure with pnpm workspaces
  - apps/, packages/, services/ organization
  - Shared dependencies and build configuration

**Development Foundation**

- ✅ Environment configuration (.env setup)
- ✅ Agent core package started (30% complete)
  - ClaudeClient implemented
  - Test infrastructure configured
- ✅ Project structure defined for all components

**Decisions Made:**

1. **Documentation Strategy** - 3-file system only (CLAUDE.md, STATUS.md,
   README.md)
2. **Monorepo Structure** - pnpm workspaces for better code sharing
3. **Database** - PostgreSQL + pgvector over separate vector DB for semantic
   search
4. **Agent Framework** - LangGraph 0.2.x with Claude Sonnet 4.5

**Next:** Week 3 - LangGraph orchestrator implementation

---

### 2025-11-01 (Week 2 - Afternoon) - Infrastructure Verification & Fixes

**Verification Completed**

- ✅ Comprehensive infrastructure audit performed
  - Docker environment: VERIFIED (all 3 services correctly configured)
  - Monorepo structure: VERIFIED (pnpm workspaces operational)
  - Git configuration: VERIFIED (.gitignore properly set up)

**Issues Identified & Fixed**

- ✅ Database schema completion (CRITICAL FIX)
  - **Problem:** Changelog claimed 6 tables, but only 4 existed
  - **Fixed:** Added missing `performance_metrics` and `user_feedback` tables
  - **Result:** All 6 tables now implemented in 001_initial.sql

- ✅ Environment template created
  - **Problem:** No .env.example for team onboarding
  - **Fixed:** Created .env.example with placeholder values
  - **Benefit:** New developers can quickly set up environment

- ✅ File structure alignment
  - **Problem:** claude-client.ts location differed from documentation
  - **Fixed:** Moved to src/clients/claude-client.ts
  - **Result:** Code structure now matches CLAUDE.md specifications

**Infrastructure Now 100% Complete**

- All 6 database tables implemented and documented
- Environment template available for onboarding
- File structure aligned with architectural documentation
- Ready for Week 3: LangGraph orchestrator implementation

**Git Repository Setup**

- ✅ Initialized git repository (master branch)
- ✅ Created private GitHub repository: autonomous-ai-platform
- ✅ Initial commit with 17 files (9,399 lines of code + documentation)
- ✅ Remote configured and pushed to GitHub
- **Repository:** https://github.com/Pkanna10/autonomous-ai-platform

---

### 2025-10-25 to 2025-10-31 (Week 1)

**Project Initialization**

- ✅ Repository created
- ✅ Initial documentation written (6,388 lines in documentation_guide/)
  - FINAL_Autonomous_AI_Platform_Implementation_Guide.md (1,797 lines)
  - Unified_Autonomous_Research_Platform_Architecture.md (4,591 lines)
- ✅ 12-month roadmap planned (52 weeks, 6 phases)
- ✅ Technology stack selected
  - Backend: Node.js 20+ (TypeScript 5.9) + Python 3.10+ (LangGraph)
  - Database: PostgreSQL 16 + pgvector, Redis 7.x, Qdrant
  - LLM: Claude Sonnet 4.5
  - Frontend: Next.js 14+ (planned)

**Decisions Made:**

1. **Timeline** - 12-month development cycle with 6 distinct phases
2. **Architecture** - 7-layer architecture design
3. **Key Innovation** - Research paper integration as differentiator

---

## Project Overview

### Executive Summary

This is an **autonomous AI development platform** designed to revolutionize solo
developer productivity by combining AI agents, research paper integration, and
self-improving systems. The platform can understand natural language
requirements, automatically discover and install packages, read research papers,
implement cutting-edge algorithms, and continuously optimize itself.

**Key Metrics:**

- 77-82% success rate on complex coding tasks (SWE-bench)
- 30+ hour continuous operation without human intervention
- 3-100x performance improvements through research-driven optimization
- 90% cost reduction via intelligent prompt caching
- 64% fewer tokens than traditional agent patterns

**Current Status:** Week 1-2 of 52 (Month 1 of 12-month timeline)

### Vision & Purpose

The platform aims to enable a **single developer to build production systems**
that would typically require a team, by:

1. **Autonomous Package Discovery** - Automatically finding and installing the
   right NPM/PyPI packages
2. **Research Paper Implementation** - Reading arXiv papers and implementing
   cutting-edge algorithms
3. **Self-Optimization** - Continuously improving code performance through
   algorithmic analysis
4. **Multi-Agent Orchestration** - Coordinating specialized AI agents for
   complex tasks
5. **Self-Healing** - Automatically detecting and fixing errors

### Key Innovation: Research-Driven Development

**Unique Differentiator:** The ability to:

1. Monitor arXiv daily for new CS papers (Data Structures, Distributed
   Computing, Databases)
2. Extract algorithms from PDFs using pattern matching + Claude AI
3. Analyze complexity and assess applicability to current problems
4. Generate production code implementing research algorithms
5. Benchmark and validate against baseline implementations

**Real Example:**

```
User Request: "Build a real-time dashboard with Google Analytics handling 1M events/day"

System Response:
1. Searches arXiv for "streaming aggregation"
2. Finds HyperLogLog paper (Flajolet et al., 2007, 8000+ citations)
3. Extracts algorithm: "Use 2^p registers, hash events, count leading zeros"
4. Generates TypeScript implementation with 0.8% error rate
5. Achieves O(1) space instead of O(n) naive approach

Result: 500K events/sec in 18KB memory (3-100x improvement)
```

---

## Architecture

### 7-Layer Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1: USER INTERFACES                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐│
│  │ Claude       │ │ Web Chat     │ │ VS Code      │ │ CLI     ││
│  │ Desktop      │ │ (Next.js)    │ │ Extension    │ │ Tool    ││
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────┬────┘│
└─────────┼────────────────┼────────────────┼───────────────┼─────┘
          │                │                │               │
┌─────────┴────────────────┴────────────────┴───────────────┴─────┐
│ LAYER 2: AI AGENT ORCHESTRATOR (LangGraph + Claude Sonnet 4.5)  │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Intent      │→ │ Task         │→ │ Execution & Reflexion  │ │
│  │ Parser      │  │ Planner      │  │ (Error Recovery)       │ │
│  └─────────────┘  └──────────────┘  └────────────────────────┘ │
└──────────┬────────────────┬─────────────────┬────────────────────┘
           │                │                 │
┌──────────┴────────────────┴─────────────────┴────────────────────┐
│ LAYER 3: CAPABILITY ACQUISITION                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Package      │ │ MCP Server   │ │ API Connector Hub        │ │
│  │ Manager      │ │ Manager      │ │ (OAuth 2.1, Vault)       │ │
│  │ (NPM/PyPI)   │ │ (48+ servers)│ │                          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└──────────┬────────────────┬─────────────────┬────────────────────┘
           │                │                 │
┌──────────┴────────────────┴─────────────────┴────────────────────┐
│ LAYER 4: RESEARCH DISCOVERY ENGINE                                │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ arXiv/ACM    │→│ PDF Parser   │→│ Algorithm Extractor      │ │
│  │ Monitor      │ │ (PyMuPDF)    │ │ (Pseudocode → AST)       │ │
│  │ (50+ papers) │ │              │ │                          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└──────────┬────────────────┬─────────────────┬────────────────────┘
           │                │                 │
┌──────────┴────────────────┴─────────────────┴────────────────────┐
│ LAYER 5: EXECUTION ENGINE                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Code         │ │ Hot Reload   │ │ Sandboxed Docker         │ │
│  │ Generator    │ │ (Vite HMR)   │ │ Execution (<100ms)       │ │
│  │ (ts-morph)   │ │              │ │                          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└──────────┬────────────────┬─────────────────┬────────────────────┘
           │                │                 │
┌──────────┴────────────────┴─────────────────┴────────────────────┐
│ LAYER 6: ADVANCED OPTIMIZATION                                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Algorithmic  │ │ Predictive   │ │ Self-Healing System      │ │
│  │ Optimizer    │ │ Pre-compute  │ │ (Auto-fix errors)        │ │
│  │ (O(n²)→O(n)) │ │ (ML-based)   │ │                          │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└──────────┬────────────────┬─────────────────┬────────────────────┘
           │                │                 │
┌──────────┴────────────────┴─────────────────┴────────────────────┐
│ LAYER 7: SELF-IMPROVEMENT                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Feedback     │→│ Performance  │→│ Continuous Optimization  │ │
│  │ Collection   │ │ Monitoring   │ │ (Prompts → Fine-tune)    │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

### Technology Stack

#### Backend

- **Runtime:** Node.js 20+ with TypeScript 5.9
- **Package Manager:** pnpm (monorepo workspace)
- **Agent Framework:** LangGraph 0.2.x (Python)
- **LLM Integration:** Anthropic SDK (Claude Sonnet 4.5)
- **Code Analysis:** ts-morph (TypeScript AST), ast/astor (Python AST)

#### Data Layer

- **Primary Database:** PostgreSQL 16 + pgvector extension
- **Vector Database:** Qdrant (self-hosted)
- **Cache/Queue:** Redis 7.x + BullMQ
- **Embeddings:** sentence-transformers (all-MiniLM-L6-v2)

#### Frontend

- **Framework:** Next.js 14+ (App Router)
- **UI Components:** shadcn/ui + Tailwind CSS
- **State Management:** Zustand
- **Hot Reload:** Vite 5.x

#### Infrastructure

- **Containerization:** Docker + Docker Compose
- **Monitoring:** Grafana + Prometheus + Loki
- **Security:** Semgrep (SAST), Socket.dev (supply chain)
- **Secret Management:** HashiCorp Vault

### Data Flow

```
User Input → Intent Parser → Task Planner
                                  ↓
                    ┌─────────────┴─────────────┐
                    ↓                           ↓
            Need Package?                Need Research?
                    ↓                           ↓
            Package Manager              Research Engine
                    ↓                           ↓
            Install Package              Extract Algorithm
                    ↓                           ↓
                    └─────────────┬─────────────┘
                                  ↓
                          Code Generator
                                  ↓
                          Sandbox Execution
                                  ↓
                          Performance Check
                                  ↓
                    ┌─────────────┴─────────────┐
                    ↓                           ↓
                Success?                    Error?
                    ↓                           ↓
            Return to User              Self-Healing System
                                                ↓
                                        Retry Execution
```

---

## Project Structure

```
autonomous-ai-platform/
├── apps/
│   ├── web/                    # Next.js frontend (NOT YET BUILT)
│   │   ├── src/
│   │   │   ├── app/           # Next.js App Router
│   │   │   ├── components/    # React components
│   │   │   └── lib/           # Client utilities
│   │   └── package.json
│   └── cli/                    # CLI interface (NOT YET BUILT)
│       ├── src/
│       │   └── commands/      # CLI commands
│       └── package.json
│
├── packages/
│   ├── agent-core/            # Core agent logic (IN PROGRESS)
│   │   ├── src/
│   │   │   ├── clients/      # ClaudeClient ✅
│   │   │   ├── orchestrator/ # LangGraph integration (TODO)
│   │   │   └── types/        # TypeScript types
│   │   └── package.json       # @anthropic-ai/sdk, pg
│   │
│   ├── research-engine/       # Research discovery (PLACEHOLDER)
│   │   ├── src/
│   │   │   ├── arxiv/        # arXiv monitoring
│   │   │   ├── parser/       # PDF parsing
│   │   │   └── extractor/    # Algorithm extraction
│   │   └── package.json
│   │
│   └── execution-engine/      # Code generation (PLACEHOLDER)
│       ├── src/
│       │   ├── generator/    # ts-morph code generation
│       │   ├── sandbox/      # Docker execution
│       │   └── optimizer/    # Performance optimization
│       └── package.json
│
├── services/
│   └── python_agents/         # Python/LangGraph services (TODO)
│       ├── orchestrator/      # Main LangGraph orchestrator
│       ├── research/          # Research agent
│       └── requirements.txt   # Python dependencies
│
├── infrastructure/
│   ├── schema/
│   │   └── 001_initial.sql   # Database schema ✅
│   ├── docker/
│   │   └── Dockerfile.*      # Service Dockerfiles (TODO)
│   └── monitoring/           # Grafana/Prometheus (TODO)
│
├── documentation_guide/       # ✅ COMPLETE (6,388 lines)
│   ├── FINAL_Autonomous_AI_Platform_Implementation_Guide.md
│   └── Unified_Autonomous_Research_Platform_Architecture.md
│
├── docker-compose.dev.yml     # ✅ Development environment
├── package.json               # ✅ Root workspace config
├── pnpm-workspace.yaml        # ✅ Monorepo setup
└── CLAUDE.md                  # ⭐ THIS FILE
```

### Current Implementation Status

| Component              | Status         | Progress |
| ---------------------- | -------------- | -------- |
| Project Setup          | ✅ Complete    | 100%     |
| Docker Environment     | ✅ Complete    | 100%     |
| Database Schema        | ✅ Complete    | 100%     |
| Agent Core Package     | 🟡 In Progress | 30%      |
| LangGraph Orchestrator | ❌ Not Started | 0%       |
| Package Manager        | ❌ Not Started | 0%       |
| Research Engine        | ❌ Not Started | 0%       |
| Code Generator         | ❌ Not Started | 0%       |
| Web UI                 | ❌ Not Started | 0%       |
| CLI Tool               | ❌ Not Started | 0%       |

---

## Database Schema

### Tables Overview

The platform uses PostgreSQL 16 with pgvector extension for semantic search
capabilities.

#### 1. packages

Tracks NPM and PyPI packages discovered and used by the system.

```sql
CREATE TABLE packages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    ecosystem VARCHAR(50) NOT NULL, -- 'npm' or 'pypi'
    version VARCHAR(100) NOT NULL,
    description TEXT,
    downloads_last_month INTEGER,
    github_stars INTEGER,
    last_updated TIMESTAMP,
    semantic_rank FLOAT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_packages_name ON packages(name);
CREATE INDEX idx_packages_ecosystem ON packages(ecosystem);
```

#### 2. research_papers

Stores arXiv papers with embeddings for semantic search.

```sql
CREATE TABLE research_papers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arxiv_id VARCHAR(50) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    authors TEXT[],
    abstract TEXT,
    pdf_url VARCHAR(500),
    published_date DATE,
    categories TEXT[],
    citation_count INTEGER,
    embedding vector(384), -- sentence-transformers embedding
    extracted_algorithms JSONB,
    complexity_analysis JSONB,
    applicability_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_papers_arxiv_id ON research_papers(arxiv_id);
CREATE INDEX idx_papers_embedding ON research_papers USING ivfflat (embedding vector_cosine_ops);
```

#### 3. generated_code

All AI-generated code with quality metrics.

```sql
CREATE TABLE generated_code (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES task_executions(id),
    file_path VARCHAR(500),
    language VARCHAR(50),
    code TEXT NOT NULL,
    imports TEXT[],
    dependencies JSONB,
    complexity_metrics JSONB,
    quality_score FLOAT,
    syntax_valid BOOLEAN,
    lint_passed BOOLEAN,
    research_paper_id UUID REFERENCES research_papers(id),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_generated_code_task ON generated_code(task_id);
```

#### 4. task_executions

End-to-end execution tracking with costs.

```sql
CREATE TABLE task_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_input TEXT NOT NULL,
    intent VARCHAR(100),
    status VARCHAR(50), -- 'pending', 'in_progress', 'success', 'failed'
    result JSONB,
    error_message TEXT,
    tokens_used INTEGER,
    cost_usd DECIMAL(10, 6),
    latency_ms INTEGER,
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
CREATE INDEX idx_task_status ON task_executions(status);
CREATE INDEX idx_task_started ON task_executions(started_at DESC);
```

#### 5. performance_metrics

Performance monitoring for optimization.

```sql
CREATE TABLE performance_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_id UUID REFERENCES generated_code(id),
    metric_type VARCHAR(100), -- 'cpu', 'memory', 'latency', 'throughput'
    value FLOAT,
    unit VARCHAR(50),
    baseline_value FLOAT,
    improvement_percent FLOAT,
    timestamp TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_metrics_code ON performance_metrics(code_id);
CREATE INDEX idx_metrics_type ON performance_metrics(metric_type);
```

#### 6. user_feedback

Learning from user interactions.

```sql
CREATE TABLE user_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID REFERENCES task_executions(id),
    code_id UUID REFERENCES generated_code(id),
    feedback_type VARCHAR(50), -- 'explicit', 'implicit'
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    user_edits JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_feedback_task ON user_feedback(task_id);
CREATE INDEX idx_feedback_type ON user_feedback(feedback_type);
```

### Migration Strategy

- **Tool:** dbmate for database migrations
- **Location:** `/infrastructure/schema/`
- **Naming:** `001_initial.sql`, `002_add_feature.sql`, etc.
- **Auto-load:** Docker Compose mounts schema directory

---

## Implementation Timeline

### 12-Month Roadmap (52 Weeks, 6 Phases)

#### Phase 1: Foundation (Weeks 1-9) ⏳ **⚠️ YOU ARE HERE - FOCUS ON THIS PHASE ONLY**

> **🚨 CRITICAL:** Only implement Phase 1 features. Do NOT jump to Phase 2+
> (code generation, optimization, multi-agent).

**Status:** Week 1-2 complete, starting Week 3

| Week | Milestone                              | Status      |
| ---- | -------------------------------------- | ----------- |
| 1-2  | Project setup, Docker, Database        | ✅ Complete |
| 3-4  | LangGraph orchestrator, Intent parsing | 🔜 Next     |
| 5-6  | Package Manager (NPM/PyPI search)      | ⏳ Upcoming |
| 7-8  | Research Engine (arXiv monitoring)     | ⏳ Upcoming |
| 9    | State persistence, Backup strategy     | ⏳ Upcoming |

**Success Criteria:**

- ✅ Detect 95%+ of package imports
- ✅ 99%+ installation success rate
- ✅ Find 50+ papers/week
- ✅ Execute code in isolated sandbox

#### Phase 2: Code Generation (Weeks 10-14)

**Focus:** ts-morph integration, HMR, sandboxed execution

| Week  | Milestone                     |
| ----- | ----------------------------- |
| 10-11 | Code generator with ts-morph  |
| 12    | Vite HMR integration (<100ms) |
| 13    | Docker sandbox execution      |
| 14    | Testing & validation          |

**Success Criteria:**

- 95%+ syntax validity
- Pass linting checks
- Sub-5s latency for simple components
- Sub-100ms HMR updates
- 99.9%+ sandbox isolation

#### Phase 3: Advanced Optimization (Weeks 15-24)

**Focus:** Research implementation, learned data structures, self-healing

| Week  | Milestone                                               |
| ----- | ------------------------------------------------------- |
| 15-17 | Research paper analysis pipeline                        |
| 18-19 | Algorithm extraction & code generation                  |
| 20-21 | Learned data structures (HyperLogLog, Count-Min Sketch) |
| 22-23 | Predictive pre-computation (ML-based)                   |
| 24    | Self-healing system                                     |

**Success Criteria:**

- 70%+ first-attempt compilation from papers
- 3-100x speedups demonstrated
- 60%+ cache hit rate
- 50%+ errors auto-fixed
- 80%+ bottlenecks detected

#### Phase 4: Multi-Agent System (Weeks 25-36)

**Focus:** MCP servers, specialized agents, OAuth flows

| Week  | Milestone                                                |
| ----- | -------------------------------------------------------- |
| 25-28 | MCP server integration (48+ servers)                     |
| 29-32 | 8 specialized agents (Code, Research, Test, Debug, etc.) |
| 33-36 | OAuth 2.1 flows, API connector hub                       |

**Success Criteria:**

- 99.9%+ MCP server uptime
- 8 agents operational
- OAuth flows for 10+ services

#### Phase 5: Polish & Features (Weeks 37-44)

**Focus:** Web UI, CLI, testing

| Week  | Milestone             |
| ----- | --------------------- |
| 37-39 | Next.js web interface |
| 40-41 | CLI tool              |
| 42-44 | 90%+ test coverage    |

**Success Criteria:**

- Production-ready UI
- CLI with 20+ commands
- 90%+ test coverage
- 4.5+/5 user satisfaction

#### Phase 6: Production Deployment (Weeks 45-52)

**Focus:** Infrastructure, monitoring, security

| Week  | Milestone                                   |
| ----- | ------------------------------------------- |
| 45-47 | Production infrastructure (Kubernetes, RDS) |
| 48-49 | Monitoring (Prometheus/Grafana)             |
| 50-51 | Security audit & penetration testing        |
| 52    | Launch & documentation                      |

**Success Criteria:**

- 99.9%+ uptime
- <2s P99 latency
- Security audit passed
- Public launch

---

## Core Features & Capabilities

### 1. Autonomous Package Discovery

**Purpose:** Automatically find and install the right NPM/PyPI packages for any
task.

**How it works:**

1. Parse user intent to detect package needs (e.g., "visualize data" → needs
   charting library)
2. Search NPM/PyPI registries with semantic ranking
3. Use Claude to rank by quality (not just download count)
4. Install in sandbox environment
5. Verify installation and track dependencies

**Key Metrics:**

- 95%+ detection rate for package needs
- 99%+ installation success rate
- Avg 2-3 packages per task

**Example:**

```
User: "Build a dashboard showing sales data"
System: Detects needs: UI framework, charting, data formatting
Searches: recharts (38k stars), date-fns (32k stars), shadcn/ui
Installs: All successfully in sandbox
```

### 2. Research Paper Implementation

**Purpose:** Read academic papers and implement cutting-edge algorithms.

**Pipeline:**

1. **Monitor:** Daily arXiv scans for CS papers (Data Structures, Databases,
   Performance)
2. **Parse:** Extract text, figures, pseudocode from PDFs
3. **Extract:** Identify algorithms using pattern matching + Claude
4. **Analyze:** Determine time/space complexity
5. **Score:** Rate applicability to current problem (0-1)
6. **Generate:** Produce TypeScript/Python implementation
7. **Validate:** Benchmark against baseline

**Key Papers Targeted:**

- HyperLogLog (streaming aggregation)
- Count-Min Sketch (approximate counting)
- Bloom filters (set membership)
- Skip lists (fast search)
- CRDT (distributed systems)

**Success Rate:**

- 70%+ first-attempt compilation from papers
- 3-100x demonstrated speedups
- 50+ papers/week processed

### 3. Intelligent Code Generation

**Purpose:** Generate type-safe, production-ready code.

**Approach:**

- **AST-based:** Uses ts-morph (TypeScript) and ast module (Python)
- **Type-safe:** Generates proper TypeScript types
- **Import resolution:** Automatically detects and adds imports
- **Template-based:** Reusable patterns for common structures
- **Research integration:** Incorporates algorithms from papers

**Quality Metrics:**

- 95%+ syntax validity
- 90%+ lint passing
- 85%+ type safety
- Sub-5s latency for simple components

**Example Output:**

```typescript
// Generated code with proper types and imports
import { HyperLogLog } from '@/lib/hyperloglog';
import { Card, CardHeader, CardTitle } from '@/components/ui/card';

interface DashboardProps {
  events: Event[];
}

export function Dashboard({ events }: DashboardProps) {
  const uniqueUsers = new HyperLogLog(14); // 2^14 registers
  events.forEach(e => uniqueUsers.add(e.userId));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Unique Users: {uniqueUsers.count()}</CardTitle>
      </CardHeader>
    </Card>
  );
}
```

### 4. Hot Module Replacement (HMR)

**Purpose:** Instant feedback loop with sub-100ms updates.

**Implementation:**

- **Vite 5.x:** Fast build tool with native HMR
- **Custom boundaries:** Preserve state across reloads
- **Error overlay:** Visual feedback for errors
- **State preservation:** Maintain React state during updates

**Performance:**

- Sub-100ms updates (target: 50ms)
- State preserved 99%+ of time
- Error recovery in <1s

### 5. Sandboxed Execution

**Purpose:** Safe, isolated code execution environment.

**Security Measures:**

- Docker containers with resource limits
- Read-only filesystem
- Network isolation (no outbound by default)
- User namespaces (non-root)
- 30s timeout enforcement
- Resource limits: 512MB RAM, 50% CPU

**Safety:**

- 99.9%+ isolation effectiveness
- Zero production incidents (target)
- Automatic cleanup after execution

### 6. Performance Optimization

**Purpose:** Automatically improve code performance.

**Optimization Levels:**

1. **Profiling:**
   - CPU sampling
   - Memory tracking
   - Hotspot detection

2. **Analysis:**
   - Big-O complexity calculation
   - Algorithmic bottleneck detection
   - Resource usage patterns

3. **Optimization:**
   - O(n²) → O(n log n) transformations
   - Learned data structures (HyperLogLog, Count-Min Sketch)
   - Caching strategies
   - Predictive pre-computation

**Results:**

- 80%+ bottleneck detection rate
- 3-100x speedups on optimizable code
- 60%+ cache hit rate

### 7. Self-Healing System

**Purpose:** Automatically detect and fix errors.

**Process:**

1. **Detect:** Monitor for errors (syntax, type, runtime)
2. **Analyze:** Understand error pattern using Claude
3. **Generate Fix:** Create patch using AI
4. **Test:** Validate fix in sandbox
5. **Deploy:** Gradual rollout (1% → 5% → 25% → 100%)

**Success Rate:**

- 50%+ auto-fix success rate
- 90%+ error detection rate
- <5min time to fix

### 8. Self-Improvement Loop

**Purpose:** Continuously improve system performance.

**Feedback Collection:**

- **Explicit:** 👍👎 ratings, comments
- **Implicit:** User edits, deletions, compile errors
- **Quality:** Syntax validity, lint passing, test passing

**Optimization Strategies:**

1. **Prompt Engineering (70% gains):** Iterative refinement
2. **Supervised Fine-tuning (20% gains):** Fine-tune on successful examples
3. **RLHF (10% gains):** Reinforcement learning from feedback

**Tracking:**

- Task success rates
- Token usage and costs
- Latency (P50, P95, P99)
- Error patterns

---

## Development Guide

### Environment Setup

#### Prerequisites

- macOS (Darwin) or Linux
- Docker Desktop
- Node.js 20+
- Python 3.10+
- pnpm 10.20.0

#### Initial Setup

```bash
# Clone repository
cd /Users/praveen/autonomous-ai-platform

# Install dependencies
pnpm install

# Start infrastructure services
docker-compose -f docker-compose.dev.yml up -d

# Verify services
docker ps  # Should see postgres, redis, qdrant

# Check database
psql postgresql://dev:devpass@localhost:5432/ai_platform
```

### Environment Variables

Create `.env` file in project root:

```bash
# Anthropic API
ANTHROPIC_API_KEY=sk-ant-api03-...

# Database
DATABASE_URL=postgresql://dev:devpass@localhost:5432/ai_platform

# Redis
REDIS_URL=redis://localhost:6379

# Qdrant
QDRANT_URL=http://localhost:6333

# Environment
NODE_ENV=development
```

### Infrastructure Services

#### PostgreSQL (Port 5432)

```yaml
Image: pgvector/pgvector:pg15
Database: ai_platform
User: dev
Password: devpass
Extensions: uuid-ossp, vector
```

#### Redis (Port 6379)

```yaml
Image: redis:7-alpine
Used for: Caching, queues, sessions, rate limiting
```

#### Qdrant (Port 6333)

```yaml
Image: qdrant/qdrant:latest
Used for: Vector embeddings, semantic search
```

### Development Workflow

1. **Start services:** `docker-compose -f docker-compose.dev.yml up -d`
2. **Install dependencies:** `pnpm install`
3. **Run tests:** `pnpm test` (when available)
4. **Build:** `pnpm build` (when available)
5. **Lint:** `pnpm lint` (when available)

### Testing Strategy

**Target: 90%+ test coverage**

**🔴🟢🔵 TDD Workflow (MANDATORY):**

Every feature MUST follow Red-Green-Refactor:

1. **RED:** Write failing test first → Verify it fails
2. **GREEN:** Write minimal code → Make test pass
3. **REFACTOR:** Clean up code → Keep tests green
4. **REPEAT:** For each requirement

**See the 🧪 Test-Driven Development (TDD) Guidelines section for complete
workflow and examples.**

#### Test Type Decision Matrix

Use this to decide which test to write:

| What You're Testing | Test Type     | Framework          | Example                       |
| ------------------- | ------------- | ------------------ | ----------------------------- |
| Pure function       | Unit          | Vitest/pytest      | `parseIntent()`               |
| Class (isolated)    | Unit          | Vitest/pytest      | `ClaudeClient` (mocked)       |
| Database query      | Integration   | Testcontainers     | `PackageRepo.findByName()`    |
| API endpoint        | Integration   | Vitest + Supertest | `POST /tasks`                 |
| External API        | Unit (mocked) | vi.mock()          | `anthropic.messages.create()` |
| User workflow       | E2E           | Playwright         | Full task creation flow       |

#### Unit Tests

- **Framework:** Vitest (TypeScript), pytest (Python)
- **Location:** `*.test.ts` (colocated with source), `*_test.py`
- **Coverage:** 90%+ of all functions/classes
- **Scope:** Pure functions, business logic, utilities
- **Speed:** Fast (<100ms per test)
- **Isolation:** Mock ALL external dependencies

**Example:**

```typescript
// packages/agent-core/src/parser/intent-parser.test.ts
describe('parseIntent', () => {
  it('should identify package installation intent', () => {
    const result = parseIntent('install lodash');
    expect(result.type).toBe('INSTALL_PACKAGE');
    expect(result.packageName).toBe('lodash');
  });
});
```

#### Integration Tests

- **Framework:** Vitest + Testcontainers (TypeScript), pytest (Python)
- **Location:** `*.integration.test.ts`, `*_integration_test.py`
- **Coverage:** 80%+ of database/API/service interactions
- **Scope:** Database queries, Redis caching, Qdrant vector search, API calls
- **Speed:** Medium (1-5s per test)
- **Setup:** Docker containers for real dependencies

**Example with Testcontainers:**

```typescript
let container: StartedPostgreSqlContainer;

beforeAll(async () => {
  container = await new PostgreSqlContainer('pgvector/pgvector:pg15').start();
}, 60000);

afterAll(async () => {
  await container.stop();
});
```

#### E2E Tests

- **Framework:** Playwright
- **Location:** `e2e/*.spec.ts`
- **Scope:** Critical user workflows (not aiming for high coverage)
- **Speed:** Slow (10-60s per test)
- **Coverage:** Essential user journeys only

**Critical Workflows:**

- Create task → Execute → View results
- Install package → Verify installation
- Search paper → Extract algorithm → Generate code

#### Mocking External Services

**Always mock external APIs in unit tests:**

```typescript
// Mock Anthropic API
vi.mock('@anthropic-ai/sdk', () => ({
  Anthropic: vi.fn().mockImplementation(() => ({
    messages: {
      create: vi.fn().mockResolvedValue({
        content: [{ text: 'Mocked response' }],
      }),
    },
  })),
}));

// Mock arXiv API
vi.spyOn(global, 'fetch').mockResolvedValue({
  json: () => Promise.resolve({ papers: [] }),
});
```

#### Test Data Management

**Use factories for consistent test data:**

```typescript
// test/factories/package.factory.ts
export function createMockPackage(overrides = {}) {
  return {
    id: randomUUID(),
    name: 'test-package',
    version: '1.0.0',
    ...overrides,
  };
}
```

**Use fixtures in pytest:**

```python
@pytest.fixture
def sample_paper():
    return Paper(title="Test", authors=["Author"])
```

#### Pre-Commit Workflow

**Required before EVERY commit:**

```bash
# Shortcut: Run all checks at once (RECOMMENDED)
pnpm run pre-commit

# OR run individually:
# 1. Run all tests
pnpm test

# 2. Verify coverage ≥90%
pnpm test:coverage

# 3. Lint code
pnpm lint

# 4. Type check
pnpm typecheck
```

**Important:** The `pnpm run pre-commit` command runs all 4 checks sequentially.
All must pass before you commit code to git.

#### Continuous Testing

**During development (recommended):**

```bash
# Watch mode - auto-run tests on changes
pnpm test:watch

# Run specific test file
pnpm test packages/agent-core/src/parser.test.ts
```

**Testing Checklist (before marking task complete):**

- [ ] Tests written FIRST (TDD Red-Green-Refactor)
- [ ] All tests passing
- [ ] Coverage ≥90% verified
- [ ] Edge cases tested (null, empty, boundaries)
- [ ] Error conditions tested
- [ ] External dependencies mocked
- [ ] Test names are descriptive
- [ ] AAA/Given-When-Then pattern followed

---

## Best Practices

### What to Build vs Buy

#### Always Buy/Use Open Source ✅

- **Authentication:** Clerk, Auth0, NextAuth
- **HMR:** Vite, Webpack (never build your own!)
- **UI Components:** shadcn/ui, Radix UI, Headless UI
- **Agent Orchestration:** LangGraph (not from scratch)
- **Code Parsing:** ts-morph, Python AST (not manual parsing)
- **Vector DB:** Qdrant, Pinecone, Weaviate
- **Monitoring:** Grafana Cloud, Datadog, New Relic
- **Email:** SendGrid, Resend, Postmark
- **Payments:** Stripe, Paddle (never build)

#### Build Only When Necessary 🔨

- Core orchestration logic
- Agent prompts and behaviors
- Feedback collection system
- Research integration pipeline
- Domain-specific optimizations
- Custom business logic

#### Never Build 🚫

- LLM inference engines
- Payment processing
- Email delivery infrastructure
- Authentication systems (from scratch)
- Security-critical infrastructure
- Standard UI components

### Common Pitfalls to Avoid

1. **Premature Optimization**
   - ❌ Optimizing before measuring
   - ✅ Profile first, then optimize hotspots

2. **Over-Engineering (YAGNI)**
   - ❌ Building features "we might need"
   - ✅ Build only what's needed now

3. **Ignoring Costs**
   - ❌ Unlimited Claude API calls
   - ✅ Cache aggressively, monitor usage

4. **Skipping Tests**
   - ❌ "I'll add tests later"
   - ✅ Test-driven development from day one

5. **Poor Documentation**
   - ❌ "Code is self-documenting"
   - ✅ Document architecture, decisions, APIs

6. **Scope Creep**
   - ❌ Adding features during development
   - ✅ Stick to MVP, iterate based on feedback

### Key Success Factors

1. **Start Small:** Ship Phase 1+2 (6 months) as MVP
2. **Get Feedback Early:** 10 beta users before adding features
3. **Iterate Weekly:** Small deployments with feature flags
4. **Monitor Everything:** Metrics-driven decisions
5. **Invest in Quality:** 90%+ test coverage from day one
6. **Leverage Existing:** Don't reinvent the wheel

---

## Success Metrics

### Technical KPIs

| Metric                 | Target | Current Status      |
| ---------------------- | ------ | ------------------- |
| Code syntax validity   | 95%+   | Not measured yet    |
| Lint passing rate      | 90%+   | Not measured yet    |
| Test coverage          | 90%+   | 0% (no tests yet)   |
| Research papers/week   | 50+    | 0 (not implemented) |
| Optimization detection | 80%+   | 0 (not implemented) |
| Self-healing success   | 50%+   | 0 (not implemented) |
| Cache hit rate         | 60%+   | 0 (not implemented) |
| API latency P99        | <2s    | Not measured        |
| System uptime          | 99.9%+ | N/A (dev only)      |
| Package detection      | 95%+   | Not measured        |
| Installation success   | 99%+   | Not measured        |

### Business KPIs

| Metric               | Target        |
| -------------------- | ------------- |
| User satisfaction    | 4.5+/5        |
| Task success rate    | 70%+          |
| Time savings         | 10x vs manual |
| Cost per task        | <$1           |
| User retention (30d) | 60%+          |
| Growth rate          | 20%+ MoM      |

### Innovation KPIs

| Metric                   | Target |
| ------------------------ | ------ |
| Papers implemented       | 20+    |
| Performance improvements | 3-100x |
| Novel combinations       | 5+     |
| Community contributions  | 10+    |
| Research citations       | 3+     |

---

## Quick Reference for Claude

> **💡 Use this checklist before starting any task**

### Pre-Flight Checklist (Read EVERY time before making changes)

1. ✅ **Current Phase:** Phase 1 - Foundation (Weeks 1-9)
2. ✅ **Write Tests FIRST:** TDD Red-Green-Refactor cycle (mandatory)
3. ✅ **Only 3 Docs:** CLAUDE.md, STATUS.md, README.md (never create others)
4. ✅ **No `any` Types:** Explicit TypeScript types always
5. ✅ **No Secrets:** Never commit API keys or passwords
6. ✅ **Monorepo Structure:** Place code in correct package location

### Decision Trees

**"Should I implement this feature?"**

```
Is it in Phase 1?
├─ YES → Proceed with implementation (TDD workflow)
└─ NO (Phase 2+) → Explain timeline to user, offer alternatives
```

**"Should I create this documentation file?"**

```
Is it CLAUDE.md, STATUS.md, or README.md?
├─ YES → Proceed with update
└─ NO → STOP! Add to CLAUDE.md or ask user first
```

**"How do I test this?"**

```
Does it have external dependencies?
├─ NO (pure function) → Unit test (Vitest/pytest, <100ms)
├─ YES (database/cache/API) → Integration test (Testcontainers, 1-5s)
└─ YES (complete workflow) → E2E test (Playwright, 10-60s)
```

### Quick Commands Reference

```bash
# Before EVERY commit
pnpm test              # All tests must pass
pnpm test:coverage     # Verify ≥90% coverage
pnpm lint              # Check code style
pnpm typecheck         # Verify types

# During development
pnpm test:watch        # Auto-run tests on changes
docker-compose -f docker-compose.dev.yml up -d  # Start services
```

### When to Ask User

**Always ask when:**

- Requirements are ambiguous or unclear
- Multiple valid approaches exist
- About to make breaking changes
- Need to deviate from Phase 1 timeline
- Encountering unexpected errors
- Need API keys/credentials

**Example:**

> "I notice this feature is planned for Phase 3 (Week 20). Would you like me to:
>
> 1. Implement a simplified version now for Phase 1
> 2. Wait until Phase 3 as planned
> 3. Adjust the timeline to prioritize this feature?"

### TDD Quick Reference

**Red-Green-Refactor Cycle:**

1. 🔴 **RED:** Write failing test → Verify it fails
2. 🟢 **GREEN:** Write minimal code → Make test pass
3. 🔵 **REFACTOR:** Clean up code → Keep tests green
4. ♻️ **REPEAT:** For each requirement

**Test Naming Pattern:**

```typescript
// ✅ Good: Descriptive, clear behavior
it('should return 404 when package not found in database');
it('should retry 3 times before failing on network errors');

// ❌ Bad: Vague, unclear
test('works');
test('package test');
```

---

## Appendix

### Useful Commands

```bash
# Docker
docker-compose -f docker-compose.dev.yml up -d     # Start services
docker-compose -f docker-compose.dev.yml down      # Stop services
docker-compose -f docker-compose.dev.yml logs -f   # View logs

# Database
psql postgresql://dev:devpass@localhost:5432/ai_platform  # Connect
\dt                                                       # List tables
\d+ research_papers                                       # Describe table

# pnpm
pnpm install                    # Install dependencies
pnpm add <package>              # Add dependency
pnpm --filter agent-core build  # Build specific package

# Development
pnpm dev                        # Start development server (when ready)
pnpm test                       # Run tests (when ready)
pnpm lint                       # Run linter (when ready)
pnpm build                      # Build all packages (when ready)
```

### Key Files Reference

| File                                                                                                                                                 | Purpose                       |
| ---------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| [docker-compose.dev.yml](docker-compose.dev.yml)                                                                                                     | Development services          |
| [infrastructure/schema/001_initial.sql](infrastructure/schema/001_initial.sql)                                                                       | Database schema               |
| [packages/agent-core/src/clients/claude.ts](packages/agent-core/src/clients/claude.ts)                                                               | Claude API client             |
| [documentation_guide/FINAL_Autonomous_AI_Platform_Implementation_Guide.md](documentation_guide/FINAL_Autonomous_AI_Platform_Implementation_Guide.md) | Detailed implementation guide |
| [documentation_guide/Unified_Autonomous_Research_Platform_Architecture.md](documentation_guide/Unified_Autonomous_Research_Platform_Architecture.md) | Architecture reference        |

### External Resources

- **Anthropic Docs:** https://docs.anthropic.com/
- **LangGraph:** https://python.langchain.com/docs/langgraph
- **ts-morph:** https://ts-morph.com/
- **PostgreSQL + pgvector:** https://github.com/pgvector/pgvector
- **Qdrant:** https://qdrant.tech/documentation/

---

**Last Updated:** 2025-11-08 (Week 2 - Configuration files enhanced with best
practices: line endings, CI reporters, dependency automation, code quality
improvements)

**Status:** Foundation phase - Early development

**Next Milestone:** LangGraph orchestrator implementation (Week 3-4)

---

_This document is the single source of truth for Claude when working on this
project. Always refer to this file before making significant changes._
