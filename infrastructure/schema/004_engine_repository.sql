-- Migration: 004_engine_repository.sql
-- Purpose: What the PostgreSQL engine Repository needs on top of 003 (Step 2)
-- Date: 2026-10-21
-- Depends on: 003_engine.sql
--
-- Every statement is idempotent so the file can run twice on the same
-- database: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, and DO-guarded
-- type changes and constraints. It adds no tables. Trials and verdicts stay
-- in the task_executions.trials / verdicts JSONB arrays that 003 designed.
--
-- Used by services/python_agents/src/autonomous_ai_agents/persistence/postgres.py.
--
-- Changes:
-- 1. task_executions: unique index on thread_id (the engine run id)
-- 2. lessons: seq identity column with a unique index (insertion order)
-- 3. lessons: gain and weight become DOUBLE PRECISION (exact round trips)
-- 4. projects: test_command JSONB (the test suite's argv), with a CHECK

-- ============================================================================
-- Change 1: task_executions.thread_id is unique
-- ============================================================================
-- Impact: One row per engine run; the repository upserts ON CONFLICT
--         (thread_id). NULLs stay distinct, so pre-engine rows are unaffected.
--         003's non-unique idx_task_thread is kept on purpose: dropping it here
--         would make a re-run of 003 recreate it.
-- Estimated time: <1 second

CREATE UNIQUE INDEX IF NOT EXISTS uq_task_thread ON task_executions(thread_id);

COMMENT ON INDEX uq_task_thread IS 'One task_executions row per engine run (thread_id = run id); target of ON CONFLICT (thread_id)';

-- ============================================================================
-- Change 2: lessons.seq
-- ============================================================================
-- Impact: list_lessons returns lessons in the order they were first saved.
--         created_at cannot do this: it is when the Lesson was built, not
--         when it was saved. Replacing a lesson (same id) keeps its seq.
-- Estimated time: <1 second (existing rows are numbered once)

ALTER TABLE lessons
  ADD COLUMN IF NOT EXISTS seq BIGINT GENERATED ALWAYS AS IDENTITY;

CREATE UNIQUE INDEX IF NOT EXISTS uq_lessons_seq ON lessons(seq);

COMMENT ON COLUMN lessons.seq IS 'Insertion order (identity); list_lessons orders by it';

-- ============================================================================
-- Change 3: lessons.gain and lessons.weight become DOUBLE PRECISION
-- ============================================================================
-- Impact: REAL is 4 bytes, so 0.4167 came back as 0.41670000553131104 and a
--         saved Lesson no longer equalled the model. Values already stored as
--         REAL keep their REAL precision. Guarded: only a REAL column changes.
-- Estimated time: <1 second on an empty table (rewrites existing rows)

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'lessons'
      AND column_name = 'gain'
      AND data_type = 'real'
  ) THEN
    ALTER TABLE lessons ALTER COLUMN gain TYPE DOUBLE PRECISION;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'lessons'
      AND column_name = 'weight'
      AND data_type = 'real'
  ) THEN
    ALTER TABLE lessons ALTER COLUMN weight TYPE DOUBLE PRECISION;
  END IF;
END
$$;

-- ============================================================================
-- Change 4: projects.test_command
-- ============================================================================
-- Impact: Project.test_command (argv of the project's test suite) survives a
--         resume. NULL means the project has no test command; otherwise it is
--         a non-empty JSON array, as workloads.command is.
-- Estimated time: <1 second

ALTER TABLE projects
  ADD COLUMN IF NOT EXISTS test_command JSONB;

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS: guard through pg_constraint.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_project_test_command_argv'
      AND conrelid = 'public.projects'::regclass
  ) THEN
    ALTER TABLE projects
      ADD CONSTRAINT chk_project_test_command_argv
      CHECK (
        test_command IS NULL
        OR (jsonb_typeof(test_command) = 'array' AND test_command <> '[]'::jsonb)
      );
  END IF;
END
$$;

COMMENT ON COLUMN projects.test_command IS 'argv of the project test suite as a non-empty JSON array; NULL when there is none';
COMMENT ON CONSTRAINT chk_project_test_command_argv ON projects IS 'test_command is NULL or a non-empty JSON array (argv), like workloads.command';

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Total changes:
-- - 0 new tables
-- - 2 new columns (lessons.seq, projects.test_command)
-- - 2 new unique indexes (uq_task_thread, uq_lessons_seq)
-- - 2 column type changes (lessons.gain, lessons.weight: REAL -> DOUBLE PRECISION)
-- - 1 DO-guarded CHECK constraint (chk_project_test_command_argv)
--
-- Re-running this file is a no-op (every statement is idempotent).
-- ============================================================================
