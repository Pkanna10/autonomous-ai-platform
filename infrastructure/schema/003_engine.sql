-- Migration: 003_engine.sql
-- Purpose: Persistence for the improvement engine (Step 1, engine design)
-- Date: 2026-10-21
-- Depends on: 001_initial.sql, 002_fix_critical_issues.sql
--
-- Every statement is idempotent so the file can run twice on the same
-- database: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, and DO-guarded
-- ADD CONSTRAINT on existing tables (Postgres has no ADD CONSTRAINT IF NOT
-- EXISTS). New timestamp columns are TIMESTAMPTZ; existing columns are left
-- untouched (chk_status on task_executions stays as it is).
--
-- Every enum CHECK list below mirrors a StrEnum in
-- services/python_agents/src/autonomous_ai_agents/common/models.py verbatim:
-- RunPhase, ObjectiveKind, Direction, GuardrailKind, ChangeClass,
-- HypothesisSource, HypothesisStatus, VerdictOutcome.
--
-- Changes:
-- 1. projects: a codebase the engine improves (new table)
-- 2. workloads: argv commands the engine runs and times (new table)
-- 3. objectives: what "better" means for one metric (new table)
-- 4. guardrails: what must not get worse (new table)
-- 5. research_papers: claims, preconditions, doi (extended)
-- 6. performance_metrics: run statistics, hardware, workload/task/trial links (extended)
-- 7. task_executions: engine run state (project, phase, trials, verdicts, ...) (extended)
-- 8. techniques: the curated playbook (new table)
-- 9. hotspots: where time and memory go, per workload (new table)
-- 10. hypotheses: ranked ideas for specific hotspots (new table)
-- 11. lessons: what verdicts taught the engine, with pgvector embeddings (new table)

-- ============================================================================
-- Change 1: projects
-- ============================================================================
-- Impact: New table; parent of workloads, objectives, guardrails, hotspots,
--         hypotheses and (optionally) lessons and task_executions
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS projects (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name VARCHAR(255) NOT NULL,
  root_path TEXT NOT NULL UNIQUE,
  default_branch VARCHAR(255) NOT NULL DEFAULT 'main',
  language VARCHAR(50) NOT NULL DEFAULT 'python',
  hardware JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE projects IS 'A codebase the engine improves; long-lived across engine runs';
COMMENT ON COLUMN projects.root_path IS 'Absolute path of the repository root (no .. segments); unique per database';
COMMENT ON COLUMN projects.default_branch IS 'Branch the engine must never push to';
COMMENT ON COLUMN projects.language IS 'Primary language of the codebase (e.g. python)';
COMMENT ON COLUMN projects.hardware IS 'Detected hardware (cpu, ram, accelerator) as a flat JSON object';

-- ============================================================================
-- Change 2: workloads
-- ============================================================================
-- Impact: New table; the unit the engine measures (baseline and every trial)
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS workloads (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  command JSONB NOT NULL,
  working_dir TEXT NOT NULL DEFAULT '.',
  entrypoint TEXT,
  inputs JSONB NOT NULL DEFAULT '{}'::jsonb,
  timeout_s REAL NOT NULL DEFAULT 600,
  warmup_runs INTEGER NOT NULL DEFAULT 1,
  runs INTEGER NOT NULL DEFAULT 5,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_workloads_project_name UNIQUE (project_id, name),
  CONSTRAINT chk_workload_command_argv
    CHECK (jsonb_typeof(command) = 'array' AND command <> '[]'::jsonb),
  CONSTRAINT chk_workload_timeout CHECK (timeout_s > 0),
  CONSTRAINT chk_workload_warmup_runs CHECK (warmup_runs >= 0),
  CONSTRAINT chk_workload_runs CHECK (runs >= 5)
);

CREATE INDEX IF NOT EXISTS idx_workloads_project ON workloads(project_id);

COMMENT ON TABLE workloads IS 'Something the engine can run and time, scoped to a project';
COMMENT ON COLUMN workloads.command IS 'argv as a non-empty JSON array of strings; never a shell string';
COMMENT ON COLUMN workloads.working_dir IS 'Working directory relative to the project root';
COMMENT ON COLUMN workloads.entrypoint IS 'Optional source file the command exercises (helps profiling)';
COMMENT ON COLUMN workloads.inputs IS 'Named inputs handed to the command as a flat JSON object';
COMMENT ON COLUMN workloads.timeout_s IS 'Per-run timeout in seconds (> 0)';
COMMENT ON COLUMN workloads.warmup_runs IS 'Untimed runs before measuring (>= 0)';
COMMENT ON COLUMN workloads.runs IS 'Timed runs per measurement; the noise rule needs >= 5';
COMMENT ON CONSTRAINT uq_workloads_project_name ON workloads IS 'Workload names are unique within a project';
COMMENT ON CONSTRAINT chk_workload_command_argv ON workloads IS 'command must be a non-empty JSON array (argv)';
COMMENT ON CONSTRAINT chk_workload_runs ON workloads IS 'Minimum 5 timed runs (MIN_RUNS in models.py)';

-- ============================================================================
-- Change 3: objectives
-- ============================================================================
-- Impact: New table; what "better" means per metric (highest weight = primary)
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS objectives (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind VARCHAR(32) NOT NULL,
  metric VARCHAR(100) NOT NULL,
  direction VARCHAR(8) NOT NULL,
  min_relative_gain REAL NOT NULL DEFAULT 0.02,
  weight REAL NOT NULL DEFAULT 1,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_objective_kind
    CHECK (kind IN ('runtime', 'peak_memory', 'throughput', 'quality_metric', 'custom')),
  CONSTRAINT chk_objective_direction CHECK (direction IN ('minimize', 'maximize')),
  CONSTRAINT chk_objective_min_relative_gain
    CHECK (min_relative_gain >= 0 AND min_relative_gain <= 1),
  CONSTRAINT chk_objective_weight CHECK (weight > 0)
);

CREATE INDEX IF NOT EXISTS idx_objectives_project ON objectives(project_id);

COMMENT ON TABLE objectives IS 'What "better" means for one metric of a project';
COMMENT ON COLUMN objectives.metric IS 'Metric name as reported by the runner (e.g. wall_time_s)';
COMMENT ON COLUMN objectives.min_relative_gain IS 'Smallest relative gain worth keeping, 0..1 (default 2%)';
COMMENT ON COLUMN objectives.weight IS 'Relative importance (> 0); the highest weight is the primary objective';
COMMENT ON CONSTRAINT chk_objective_kind ON objectives IS 'Valid values (ObjectiveKind): runtime, peak_memory, throughput, quality_metric, custom';
COMMENT ON CONSTRAINT chk_objective_direction ON objectives IS 'Valid values (Direction): minimize, maximize';

-- ============================================================================
-- Change 4: guardrails
-- ============================================================================
-- Impact: New table; what must not get worse while optimizing
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS guardrails (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  kind VARCHAR(32) NOT NULL,
  metric VARCHAR(100),
  max_drop REAL,
  direction VARCHAR(8),
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_guardrail_kind
    CHECK (kind IN ('output_equivalence', 'tests_pass', 'metric_bound')),
  CONSTRAINT chk_guardrail_max_drop CHECK (max_drop >= 0),
  CONSTRAINT chk_guardrail_direction CHECK (direction IN ('minimize', 'maximize')),
  CONSTRAINT chk_guardrail_metric_bound_complete
    CHECK (
      kind <> 'metric_bound'
      OR (metric IS NOT NULL AND max_drop IS NOT NULL AND direction IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_guardrails_project ON guardrails(project_id);

COMMENT ON TABLE guardrails IS 'What must not get worse; a metric_bound guardrail needs metric, max_drop and direction';
COMMENT ON COLUMN guardrails.max_drop IS 'Largest tolerated relative drop of the metric (>= 0); NULL unless metric_bound';
COMMENT ON CONSTRAINT chk_guardrail_kind ON guardrails IS 'Valid values (GuardrailKind): output_equivalence, tests_pass, metric_bound';
COMMENT ON CONSTRAINT chk_guardrail_direction ON guardrails IS 'Valid values (Direction): minimize, maximize, or NULL';
COMMENT ON CONSTRAINT chk_guardrail_metric_bound_complete ON guardrails IS 'Mirrors Guardrail._metric_bound_is_complete in models.py';

-- ============================================================================
-- Change 5: research_papers gains claims, preconditions and doi
-- ============================================================================
-- Impact: Papers carry Claude-extracted claims and preconditions for the matcher
-- Estimated time: <1 second (defaults are applied without a rewrite on PG 11+)

ALTER TABLE research_papers
  ADD COLUMN IF NOT EXISTS claims JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS preconditions JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS doi VARCHAR(100);

CREATE INDEX IF NOT EXISTS idx_papers_claims ON research_papers USING GIN (claims);
CREATE INDEX IF NOT EXISTS idx_papers_preconditions ON research_papers USING GIN (preconditions);

COMMENT ON COLUMN research_papers.claims IS 'JSON array of Claim objects (statement, expected_gain, preconditions, confidence)';
COMMENT ON COLUMN research_papers.preconditions IS 'JSON array of Precondition objects (description, check, required)';
CREATE UNIQUE INDEX IF NOT EXISTS idx_papers_doi
  ON research_papers(doi) WHERE doi IS NOT NULL;

COMMENT ON COLUMN research_papers.doi IS 'Digital Object Identifier, when known';
COMMENT ON INDEX idx_papers_claims IS 'Enables queries like: claims @> [{"statement": "..."}]';
COMMENT ON INDEX idx_papers_preconditions IS 'Enables queries on precondition check keys';

-- ============================================================================
-- Change 6: performance_metrics gains run statistics and engine links
-- ============================================================================
-- Impact: A row can describe N runs (mean, stdev, min, max) instead of one value,
--         and link to the workload, engine run and trial it measured
-- Estimated time: <1 second

ALTER TABLE performance_metrics
  ADD COLUMN IF NOT EXISTS run_stats JSONB,
  ADD COLUMN IF NOT EXISTS hardware JSONB,
  ADD COLUMN IF NOT EXISTS workload_id UUID REFERENCES workloads(id),
  ADD COLUMN IF NOT EXISTS task_id UUID REFERENCES task_executions(id),
  ADD COLUMN IF NOT EXISTS trial_id UUID,
  ADD COLUMN IF NOT EXISTS output_fingerprint VARCHAR(64);

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS: guard through pg_constraint.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_metrics_run_stats_n'
      AND conrelid = 'public.performance_metrics'::regclass
  ) THEN
    ALTER TABLE performance_metrics
      ADD CONSTRAINT chk_metrics_run_stats_n
      CHECK (run_stats IS NULL OR (run_stats->>'n')::int >= 1);
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_metrics_workload ON performance_metrics(workload_id);
CREATE INDEX IF NOT EXISTS idx_metrics_task ON performance_metrics(task_id);
CREATE INDEX IF NOT EXISTS idx_metrics_run_stats ON performance_metrics USING GIN (run_stats);

COMMENT ON COLUMN performance_metrics.run_stats IS 'RunStats JSON: n, mean, stdev, min, max, unit over repeated runs';
COMMENT ON COLUMN performance_metrics.hardware IS 'Hardware the measurement was taken on, as a flat JSON object';
COMMENT ON COLUMN performance_metrics.workload_id IS 'Workload that was measured';
COMMENT ON COLUMN performance_metrics.task_id IS 'Engine run (task_executions) the measurement belongs to';
COMMENT ON COLUMN performance_metrics.trial_id IS 'Trial id from task_executions.trials; NULL for the baseline';
COMMENT ON COLUMN performance_metrics.output_fingerprint IS 'sha256 hex of the workload output, for the equivalence judge';
COMMENT ON CONSTRAINT chk_metrics_run_stats_n ON performance_metrics IS 'run_stats.n must be >= 1 when run_stats is present';
COMMENT ON INDEX idx_metrics_run_stats IS 'Enables queries like: run_stats @> {"unit": "s"}';

-- ============================================================================
-- Change 7: task_executions becomes the engine run record
-- ============================================================================
-- Impact: One row per engine run: project, LangGraph thread, phase, trials,
--         verdicts, delivery and baseline. Existing columns and chk_status are
--         left untouched.
-- Estimated time: <1 second

ALTER TABLE task_executions
  ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(id),
  ADD COLUMN IF NOT EXISTS thread_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS phase VARCHAR(32),
  ADD COLUMN IF NOT EXISTS objective_ids UUID[],
  ADD COLUMN IF NOT EXISTS trials JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS verdicts JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS delivery JSONB,
  ADD COLUMN IF NOT EXISTS baseline JSONB;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_task_phase'
      AND conrelid = 'public.task_executions'::regclass
  ) THEN
    ALTER TABLE task_executions
      ADD CONSTRAINT chk_task_phase
      CHECK (
        phase IS NULL
        OR phase IN (
          'connect', 'understand', 'define', 'baseline', 'profile', 'research',
          'hypotheses', 'trials', 'judges', 'verdicts', 'approval', 'combine',
          'deliver', 'learn', 'watch', 'done', 'failed'
        )
      );
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_task_project ON task_executions(project_id);
CREATE INDEX IF NOT EXISTS idx_task_thread ON task_executions(thread_id);
CREATE INDEX IF NOT EXISTS idx_task_trials ON task_executions USING GIN (trials);
CREATE INDEX IF NOT EXISTS idx_task_verdicts ON task_executions USING GIN (verdicts);

COMMENT ON COLUMN task_executions.project_id IS 'Project the engine run improves';
COMMENT ON COLUMN task_executions.thread_id IS 'LangGraph checkpoint thread id of the run (for resume)';
COMMENT ON COLUMN task_executions.phase IS 'Current engine loop phase (RunPhase); NULL for pre-engine rows';
COMMENT ON COLUMN task_executions.objective_ids IS 'Objectives the run optimizes, in priority order';
COMMENT ON COLUMN task_executions.trials IS 'JSON array of Trial objects';
COMMENT ON COLUMN task_executions.verdicts IS 'JSON array of Verdict objects';
COMMENT ON COLUMN task_executions.delivery IS 'Delivery object (branch or PR plus report); NULL until delivered';
COMMENT ON COLUMN task_executions.baseline IS 'Baseline object: commit, measurements, objectives, guardrails';
COMMENT ON CONSTRAINT chk_task_phase ON task_executions IS 'Valid values (RunPhase): connect, understand, define, baseline, profile, research, hypotheses, trials, judges, verdicts, approval, combine, deliver, learn, watch, done, failed, or NULL';
COMMENT ON INDEX idx_task_thread IS 'Speeds up resume lookups by LangGraph thread id';
COMMENT ON INDEX idx_task_trials IS 'Enables queries on the trials JSONB array';
COMMENT ON INDEX idx_task_verdicts IS 'Enables queries on the verdicts JSONB array';

-- ============================================================================
-- Change 8: techniques (the playbook)
-- ============================================================================
-- Impact: New table; curated techniques with preconditions and expected gain
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS techniques (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  slug VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(255) NOT NULL,
  summary TEXT NOT NULL,
  change_class VARCHAR(16) NOT NULL,
  preconditions JSONB NOT NULL DEFAULT '[]'::jsonb,
  expected_gain REAL NOT NULL,
  provability REAL NOT NULL,
  risk REAL NOT NULL,
  refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_technique_change_class
    CHECK (change_class IN ('efficiency', 'behaviour', 'novel')),
  CONSTRAINT chk_technique_expected_gain CHECK (expected_gain >= 0),
  CONSTRAINT chk_technique_provability CHECK (provability >= 0 AND provability <= 1),
  CONSTRAINT chk_technique_risk CHECK (risk >= 0 AND risk <= 1)
);

COMMENT ON TABLE techniques IS 'Curated playbook: known techniques with preconditions and expected gain';
COMMENT ON COLUMN techniques.slug IS 'Stable machine key (e.g. cache-frozen-encoder-embeddings)';
COMMENT ON COLUMN techniques.change_class IS 'Drives autonomy: efficiency ships, behaviour is flagged, novel needs approval';
COMMENT ON COLUMN techniques.preconditions IS 'JSON array of Precondition objects the matcher evaluates';
COMMENT ON COLUMN techniques.expected_gain IS 'Typical relative gain (>= 0)';
COMMENT ON COLUMN techniques.provability IS 'How well the judges can prove the gain, 0..1';
COMMENT ON COLUMN techniques.risk IS 'Chance of breaking behaviour, 0..1';
COMMENT ON COLUMN techniques.refs IS 'JSON array of references (papers, docs, URLs); named refs because REFERENCES is reserved';
COMMENT ON CONSTRAINT chk_technique_change_class ON techniques IS 'Valid values (ChangeClass): efficiency, behaviour, novel';

-- ============================================================================
-- Change 9: hotspots
-- ============================================================================
-- Impact: New table; profiler findings per project and workload
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS hotspots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  workload_id UUID NOT NULL REFERENCES workloads(id) ON DELETE CASCADE,
  task_id UUID REFERENCES task_executions(id),
  file_path TEXT NOT NULL,
  symbol TEXT NOT NULL,
  line_start INTEGER,
  line_end INTEGER,
  self_time_s REAL,
  total_time_s REAL,
  share REAL,
  calls BIGINT,
  memory_bytes BIGINT,
  tags TEXT[] NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_hotspot_share CHECK (share >= 0 AND share <= 1),
  CONSTRAINT chk_hotspot_times CHECK (self_time_s >= 0 AND total_time_s >= 0)
);

CREATE INDEX IF NOT EXISTS idx_hotspots_project_workload ON hotspots(project_id, workload_id);
CREATE INDEX IF NOT EXISTS idx_hotspots_task ON hotspots(task_id);

COMMENT ON TABLE hotspots IS 'Where time or memory goes, as found by the profiler';
COMMENT ON COLUMN hotspots.file_path IS 'Source file relative to the project root';
COMMENT ON COLUMN hotspots.symbol IS 'Function, method or loop label';
COMMENT ON COLUMN hotspots.share IS 'Share of total workload time, 0..1';
COMMENT ON COLUMN hotspots.tags IS 'Matcher tags such as hot_loop, io_bound, frozen_encoder';
COMMENT ON COLUMN hotspots.task_id IS 'Engine run that profiled it, when known';

-- ============================================================================
-- Change 10: hypotheses
-- ============================================================================
-- Impact: New table; ranked ideas tied to hotspots, techniques, papers and runs
-- Estimated time: <1 second

CREATE TABLE IF NOT EXISTS hypotheses (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id UUID REFERENCES task_executions(id),
  technique_id UUID REFERENCES techniques(id),
  paper_id UUID REFERENCES research_papers(id),
  source VARCHAR(16) NOT NULL,
  hotspot_ids UUID[] NOT NULL DEFAULT '{}',
  title TEXT NOT NULL,
  rationale TEXT NOT NULL,
  change_class VARCHAR(16) NOT NULL,
  expected_gain REAL NOT NULL,
  provability REAL NOT NULL,
  risk REAL NOT NULL,
  score REAL NOT NULL DEFAULT 0,
  status VARCHAR(16) NOT NULL DEFAULT 'proposed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_hypothesis_source
    CHECK (source IN ('playbook', 'paper', 'novel', 'lesson')),
  CONSTRAINT chk_hypothesis_change_class
    CHECK (change_class IN ('efficiency', 'behaviour', 'novel')),
  CONSTRAINT chk_hypothesis_expected_gain CHECK (expected_gain >= 0),
  CONSTRAINT chk_hypothesis_provability CHECK (provability >= 0 AND provability <= 1),
  CONSTRAINT chk_hypothesis_risk CHECK (risk >= 0 AND risk <= 1),
  CONSTRAINT chk_hypothesis_status
    CHECK (status IN ('proposed', 'trialled', 'kept', 'rejected', 'inconclusive'))
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_project_status ON hypotheses(project_id, status);
CREATE INDEX IF NOT EXISTS idx_hypotheses_task ON hypotheses(task_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_score ON hypotheses(score DESC);

COMMENT ON TABLE hypotheses IS 'A ranked idea for improving specific hotspots';
COMMENT ON COLUMN hypotheses.hotspot_ids IS 'Hotspots the hypothesis targets (ids from hotspots)';
COMMENT ON COLUMN hypotheses.score IS 'expected_gain * provability * (1 - risk) * (1 + lesson_boost)';
COMMENT ON CONSTRAINT chk_hypothesis_source ON hypotheses IS 'Valid values (HypothesisSource): playbook, paper, novel, lesson';
COMMENT ON CONSTRAINT chk_hypothesis_change_class ON hypotheses IS 'Valid values (ChangeClass): efficiency, behaviour, novel';
COMMENT ON CONSTRAINT chk_hypothesis_status ON hypotheses IS 'Valid values (HypothesisStatus): proposed, trialled, kept, rejected, inconclusive';
COMMENT ON INDEX idx_hypotheses_score IS 'Optimizes queries: ORDER BY score DESC';

-- ============================================================================
-- Change 11: lessons
-- ============================================================================
-- Impact: New table; the self-improvement store that feeds hypothesis ranking
-- Estimated time: <1 second (ivfflat index is built on an empty table)

CREATE TABLE IF NOT EXISTS lessons (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
  task_id UUID REFERENCES task_executions(id),
  hypothesis_id UUID REFERENCES hypotheses(id) ON DELETE SET NULL,
  technique_id UUID REFERENCES techniques(id),
  verdict_id UUID,
  context TEXT[] NOT NULL DEFAULT '{}',
  outcome VARCHAR(16) NOT NULL,
  gain REAL,
  text TEXT NOT NULL,
  weight REAL NOT NULL DEFAULT 1,
  embedding VECTOR(384),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT chk_lesson_outcome
    CHECK (outcome IN ('keep', 'reject', 'inconclusive', 'needs_approval')),
  CONSTRAINT chk_lesson_weight CHECK (weight > 0)
);

CREATE INDEX IF NOT EXISTS idx_lessons_project_outcome ON lessons(project_id, outcome);
CREATE INDEX IF NOT EXISTS idx_lessons_context ON lessons USING GIN (context);
CREATE INDEX IF NOT EXISTS idx_lessons_embedding ON lessons
  USING ivfflat (embedding vector_cosine_ops);

COMMENT ON TABLE lessons IS 'What a verdict taught the engine; feeds the next hypothesis ranking';
COMMENT ON COLUMN lessons.project_id IS 'NULL means the lesson is global (applies to every project)';
COMMENT ON COLUMN lessons.verdict_id IS 'Verdict id from task_executions.verdicts (no FK: verdicts live in JSONB)';
COMMENT ON COLUMN lessons.context IS 'Context tags such as frozen_encoder, repeated_epochs';
COMMENT ON COLUMN lessons.gain IS 'Relative gain the verdict measured, when applicable';
COMMENT ON COLUMN lessons.weight IS 'Influence on ranking (> 0)';
COMMENT ON COLUMN lessons.embedding IS 'Embedding of text for semantic lookup (384 dims, cosine)';
COMMENT ON CONSTRAINT chk_lesson_outcome ON lessons IS 'Valid values (VerdictOutcome): keep, reject, inconclusive, needs_approval';
COMMENT ON INDEX idx_lessons_context IS 'Enables queries like: context @> ARRAY[''frozen_encoder'']';
COMMENT ON INDEX idx_lessons_embedding IS 'Approximate nearest-neighbour search on lesson embeddings';

-- ============================================================================
-- Verification: Display all tables
-- ============================================================================
SELECT
  schemaname,
  tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- ============================================================================
-- Verification: Display all indexes
-- ============================================================================
SELECT
  schemaname,
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;

-- ============================================================================
-- Verification: Display all constraints
-- ============================================================================
SELECT
  conrelid::regclass AS table_name,
  conname AS constraint_name,
  contype AS constraint_type,
  pg_get_constraintdef(oid) AS constraint_definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY table_name, constraint_name;

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Total changes:
-- - 8 new tables (projects, workloads, objectives, guardrails, techniques,
--   hotspots, hypotheses, lessons)
-- - 17 new columns on existing tables (research_papers: 3,
--   performance_metrics: 6, task_executions: 8)
-- - 20 new indexes (10 single-column, 3 composite, 6 GIN, 1 ivfflat)
-- - 2 DO-guarded CHECK constraints on existing tables
--   (chk_metrics_run_stats_n, chk_task_phase)
-- - 26 inline CHECK constraints, 3 UNIQUE constraints (projects.root_path,
--   techniques.slug, workloads(project_id, name)) and 14 foreign keys on the
--   new tables, plus 3 foreign keys on the extended tables
--   (performance_metrics.workload_id, performance_metrics.task_id,
--   task_executions.project_id)
--
-- Expected execution time: <5 seconds on an empty database
-- Re-running this file is a no-op (every statement is idempotent).
-- ============================================================================
