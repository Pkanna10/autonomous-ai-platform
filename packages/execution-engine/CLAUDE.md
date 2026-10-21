# Execution Engine Package - Claude Code Configuration

**Package:** `@autonomous-ai/execution-engine` **Version:** 4.0.0 **Primary
Language:** TypeScript 5.9+ **Testing:** Vitest **Status:** placeholder

---

## Package Purpose

Layer 5 (execution) for TypeScript codebases: AST-based code edits with
`ts-morph`, and TypeScript-specific profiling adapters, once the engine supports
TypeScript workloads.

Today the package exports a single `PLACEHOLDER` constant so the monorepo
builds. The engine's execution layer is being built first in Python
(`services/python_agents`): local runner, git worktrees per trial, profilers.
See the root `CLAUDE.md` for the build order.

---

## When Work Starts Here

- Follow the TypeScript patterns in `packages/agent-core/CLAUDE.md` (strict
  types, no `any`, Vitest AAA tests).
- Every code transformation must be reversible and run inside a git worktree,
  never on the user's working tree.
- Trial code must not be able to edit benchmark, test or judge files; the Python
  judges reject such diffs and this package must do the same.

---

## Key Files

| File           | Status  | Purpose                                   |
| -------------- | ------- | ----------------------------------------- |
| `src/index.ts` | exists  | Placeholder export                        |
| `src/edit/`    | planned | ts-morph based transformations            |
| `src/profile/` | planned | Node.js CPU and memory profiling adapters |

---

**Version:** 4.0.0 **Last Updated:** 2026-10-21
