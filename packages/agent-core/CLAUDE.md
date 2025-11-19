# Agent Core Package - Claude Code Configuration

**Package:** `@autonomous-ai/agent-core` **Version:** 3.0.0 **Primary
Language:** TypeScript 5.9+ **Runtime:** Node.js 20+ **Testing:** Vitest

---

## 📚 Advanced Prompting Techniques

**IMPORTANT:** This file contains package-specific patterns. For advanced
prompting techniques, see root `CLAUDE.md`:

- **Meta-Cognitive Thinking** - Use `<thinking>` tags before complex tasks
- **Meta-Prompting** - Decompose complex tasks (+30% improvement)
- **Graph of Thoughts** - Non-linear reasoning for complex problems (+62%)
- **26 Principled Instructions** - Evidence-based quality patterns (+57.7%)
- **Constitutional AI** - Multi-round critique for code quality (95%+
  vulnerability block)
- **XML-Structured Prompting** - Use standard tags for clarity (40%+
  performance)
- **Chain of Density** - Optimal summarization technique

**Apply these patterns when working in this package.**

---

## 🎯 Package Purpose

Core AI agent orchestration logic using LangGraph and Claude Sonnet 4.5. Handles
intent parsing, task planning, execution coordination, and database
interactions.

---

## 🔧 TypeScript Strict Mode Patterns

### Type Safety Requirements

```typescript
// ✅ GOOD: Explicit types, no any
interface AgentState {
  messages: Message[];
  intent: Intent | null;
  context: Record<string, unknown>;
}

async function parseIntent(input: string): Promise<Intent> {
  // Implementation
}

// ❌ BAD: Any types
function processTask(data: any): any {
  // Never do this
}
```

### Null Safety

```typescript
// ✅ GOOD: Handle nulls explicitly
const package = await repo.findByName(name);
if (!package) {
  throw new PackageNotFoundError(name);
}
return package;

// ❌ BAD: Assume non-null
return (await repo.findByName(name))!.version; // Dangerous!
```

---

## 🧪 Vitest Testing Patterns

### AAA Pattern (Arrange-Act-Assert)

```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('IntentParser', () => {
  let parser: IntentParser;

  beforeEach(() => {
    parser = new IntentParser();
  });

  it('should detect package installation intent from user input', () => {
    // ARRANGE
    const input = 'install lodash for utility functions';

    // ACT
    const intent = parser.parse(input);

    // ASSERT
    expect(intent.type).toBe(IntentType.INSTALL_PACKAGE);
    expect(intent.packageName).toBe('lodash');
  });
});
```

### Mocking Claude API

```typescript
import { vi } from 'vitest';

// Mock the Anthropic SDK
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
  it('should send message and receive response', async () => {
    const client = new ClaudeClient();
    const response = await client.chat([{ role: 'user', content: 'Test' }]);
    expect(response.content[0].text).toBe('Mocked response');
  });
});
```

---

## 🤖 LangGraph Agent Orchestration

### State Machine Pattern

```typescript
import { StateGraph } from '@langchain/langgraph';

// Define agent state
interface AgentState {
  messages: Message[];
  intent: Intent | null;
  plan: TaskPlan | null;
  result: ExecutionResult | null;
}

// Create graph
const graph = new StateGraph<AgentState>({
  channels: {
    messages: { reducer: (a, b) => [...a, ...b] },
    intent: { reducer: (_, b) => b },
    plan: { reducer: (_, b) => b },
    result: { reducer: (_, b) => b },
  },
});

// Add nodes
graph.addNode('parse_intent', parseIntentNode);
graph.addNode('plan_task', planTaskNode);
graph.addNode('execute', executeNode);

// Add edges
graph.addEdge('parse_intent', 'plan_task');
graph.addEdge('plan_task', 'execute');
graph.setEntryPoint('parse_intent');
graph.setFinishPoint('execute');

const app = graph.compile();
```

### Error Recovery (Reflexion Pattern)

```typescript
// Add conditional edges for error recovery
graph.addConditionalEdges('execute', (state) => {
  if (state.result?.success) {
    return 'finish';
  } else {
    return 'reflect_and_retry';
  }
});

graph.addNode('reflect_and_retry', async (state) => {
  const reflection = await claudeClient.chat([
    {
      role: 'user',
      content: `Error occurred: ${state.result?.error}. How can we fix this?`,
    },
  ]);
  return { messages: [...state.messages, reflection] };
});

graph.addEdge('reflect_and_retry', 'execute');
```

---

## 🔌 Claude API Client Usage

### Basic Chat Pattern

```typescript
import { ClaudeClient } from './clients/claude-client';

const client = new ClaudeClient();

const response = await client.chat([
  { role: 'user', content: 'Parse this intent: install lodash' },
]);

console.log(response.content[0].text);
```

### Streaming Pattern

```typescript
const stream = await client.streamChat(
  [{ role: 'user', content: 'Generate code for...' }],
  {
    onChunk: (chunk) => {
      process.stdout.write(chunk.delta.text);
    },
  }
);
```

### Tool Use Pattern

```typescript
const response = await client.chat(
  [{ role: 'user', content: 'Search for lodash package' }],
  {
    tools: [
      {
        name: 'search_npm',
        description: 'Search NPM registry for packages',
        input_schema: {
          type: 'object',
          properties: {
            query: { type: 'string' },
          },
          required: ['query'],
        },
      },
    ],
  }
);

// Handle tool calls
if (response.stop_reason === 'tool_use') {
  const toolUse = response.content.find((c) => c.type === 'tool_use');
  const result = await executeToolCall(toolUse);
  // Continue conversation with tool result...
}
```

---

## 🗄️ Database Access Patterns

### Repository Pattern (PostgreSQL + pg)

```typescript
import { Client } from 'pg';

export class PackageRepository {
  constructor(private db: Client) {}

  async findByName(name: string): Promise<Package | null> {
    const result = await this.db.query(
      'SELECT * FROM packages WHERE name = $1',
      [name]
    );
    return result.rows[0] || null;
  }

  async save(pkg: Package): Promise<void> {
    await this.db.query(
      `INSERT INTO packages (id, name, version, ecosystem, metadata)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (id) DO UPDATE SET
         version = EXCLUDED.version,
         metadata = EXCLUDED.metadata`,
      [pkg.id, pkg.name, pkg.version, pkg.ecosystem, pkg.metadata]
    );
  }
}
```

### Transaction Pattern

```typescript
async function executeTaskWithMetrics(task: Task) {
  const client = await pool.connect();

  try {
    await client.query('BEGIN');

    // Insert task execution
    const taskResult = await client.query(
      'INSERT INTO task_executions (user_input, intent) VALUES ($1, $2) RETURNING id',
      [task.input, task.intent]
    );

    // Insert generated code
    await client.query(
      'INSERT INTO generated_code (task_id, code, language) VALUES ($1, $2, $3)',
      [taskResult.rows[0].id, task.code, 'typescript']
    );

    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}
```

### Vector Search Pattern (pgvector)

```typescript
import { getEmbedding } from './embeddings';

async function findSimilarPapers(query: string, limit = 5) {
  const embedding = await getEmbedding(query);

  const result = await db.query(
    `SELECT id, title, abstract,
            1 - (embedding <=> $1::vector) AS similarity
     FROM research_papers
     ORDER BY embedding <=> $1::vector
     LIMIT $2`,
    [JSON.stringify(embedding), limit]
  );

  return result.rows;
}
```

---

## ⚡ Performance Patterns

### Batch Operations

```typescript
// ✅ GOOD: Batch insert
async function savePackages(packages: Package[]) {
  const values = packages
    .map(
      (_, i) => `($${i * 4 + 1}, $${i * 4 + 2}, $${i * 4 + 3}, $${i * 4 + 4})`
    )
    .join(',');

  const params = packages.flatMap((p) => [
    p.id,
    p.name,
    p.version,
    p.ecosystem,
  ]);

  await db.query(
    `INSERT INTO packages (id, name, version, ecosystem) VALUES ${values}`,
    params
  );
}

// ❌ BAD: Individual inserts
for (const pkg of packages) {
  await repo.save(pkg); // Slow!
}
```

---

## 🔒 Security Checklist

- [ ] All database queries use parameterized statements (no SQL injection)
- [ ] User input validated before processing
- [ ] Claude API key stored in environment variables (never hardcoded)
- [ ] Error messages don't leak sensitive information
- [ ] Rate limiting implemented for external API calls

---

## 📁 Key Files

| File                                  | Purpose                      |
| ------------------------------------- | ---------------------------- |
| `src/clients/claude-client.ts`        | Claude API wrapper           |
| `src/orchestrator/agent.ts`           | LangGraph state machine      |
| `src/parsers/intent-parser.ts`        | User intent detection        |
| `src/repositories/package-repo.ts`    | Package database access      |
| `src/repositories/task-repo.ts`       | Task execution tracking      |
| `src/__tests__/intent-parser.test.ts` | Intent parser unit tests     |
| `src/__tests__/claude-client.test.ts` | Claude client tests (mocked) |

---

**Version:** 3.0.0 **Last Updated:** 2025-11-19

**Changelog:**

- **3.0.0 (2025-11-19):** Added advanced prompting technique references
  (Meta-Cognitive, Meta-Prompting, GoT, Constitutional AI, XML structuring,
  Chain of Density)
- **2.0.0 (2025-11-19):** Initial hierarchical structure implementation with
  TypeScript/Vitest/LangGraph patterns
