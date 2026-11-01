-- Migration: 005_lesson_ids.sql
-- Purpose: Lesson hypothesis and technique ids hold the engine's caller ids
--          (Step 3, unit U1)
-- Date: 2026-10-24
-- Depends on: 003_engine.sql, 004_engine_repository.sql
--
-- Every statement is idempotent so the file can run twice on the same
-- database: the type change runs only on a UUID column, each constraint is
-- added only when pg_constraint does not hold it yet, and COMMENT replaces.
--
-- Used by services/python_agents/src/autonomous_ai_agents/persistence/postgres.py,
-- which checks the same rule (validate_run_id) before any SQL; the CHECKs
-- below refuse a direct insert that skips the code.
--
-- Changes:
-- 1. lessons.hypothesis_id and lessons.technique_id become VARCHAR(64)
-- 2. a CHECK per column encoding the engine's id rule

-- ============================================================================
-- Change 1: lessons.hypothesis_id and lessons.technique_id become VARCHAR(64)
-- ============================================================================
-- Impact: A caller hypothesis id such as 'h1' and a playbook slug such as
--         'set-membership' can be stored. Before, the UUID type refused them
--         after the run had already spent on the trial. Neither column has a
--         foreign key (hypotheses and techniques are matched by equality in
--         ranking), so the UUID type asserted something that was not true.
--         Legacy UUIDs are 36 characters and keep their text. Engine-made ids
--         (id, project_id, verdict_id) stay UUID.
-- Estimated time: <1 second on an empty table (rewrites existing rows)

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'lessons'
      AND column_name = 'hypothesis_id'
      AND data_type = 'uuid'
  ) THEN
    ALTER TABLE lessons
      ALTER COLUMN hypothesis_id TYPE VARCHAR(64) USING hypothesis_id::text;
  END IF;
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'lessons'
      AND column_name = 'technique_id'
      AND data_type = 'uuid'
  ) THEN
    ALTER TABLE lessons
      ALTER COLUMN technique_id TYPE VARCHAR(64) USING technique_id::text;
  END IF;
END
$$;

-- ============================================================================
-- Change 2: the engine's id rule as a CHECK on each column
-- ============================================================================
-- Impact: The same rule as validate_run_id (orchestrator/state.py,
--         RUN_ID_PATTERN): 1-64 letters, digits, '.', '_' or '-', a letter or
--         digit first, no '..', no trailing '.lock' or '.'. NULL stays allowed
--         (a lesson that names no hypothesis or technique). The 64-character
--         limit is also the column width, which refuses a longer value first.
-- Estimated time: <1 second (validates existing rows)

-- Postgres has no ADD CONSTRAINT IF NOT EXISTS: guard through pg_constraint.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_lesson_hypothesis_id'
      AND conrelid = 'public.lessons'::regclass
  ) THEN
    ALTER TABLE lessons
      ADD CONSTRAINT chk_lesson_hypothesis_id
      CHECK (
        hypothesis_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
        AND hypothesis_id NOT LIKE '%..%'
        AND hypothesis_id !~ '(\.lock|\.)$'
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_lesson_technique_id'
      AND conrelid = 'public.lessons'::regclass
  ) THEN
    ALTER TABLE lessons
      ADD CONSTRAINT chk_lesson_technique_id
      CHECK (
        technique_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
        AND technique_id NOT LIKE '%..%'
        AND technique_id !~ '(\.lock|\.)$'
      );
  END IF;
END
$$;

COMMENT ON COLUMN lessons.hypothesis_id IS 'Hypothesis id (a caller id such as h1, or an engine uuid); engine id rule, no FK';
COMMENT ON COLUMN lessons.technique_id IS 'Technique id (a playbook slug such as set-membership, or a uuid); engine id rule, no FK';
COMMENT ON CONSTRAINT chk_lesson_hypothesis_id ON lessons IS 'Same rule as validate_run_id: 1-64 of [A-Za-z0-9._-], alphanumeric first, no .., no trailing .lock or .';
COMMENT ON CONSTRAINT chk_lesson_technique_id ON lessons IS 'Same rule as validate_run_id: 1-64 of [A-Za-z0-9._-], alphanumeric first, no .., no trailing .lock or .';

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Total changes:
-- - 0 new tables, 0 new columns
-- - 2 column type changes (lessons.hypothesis_id, lessons.technique_id:
--   UUID -> VARCHAR(64))
-- - 2 DO-guarded CHECK constraints (chk_lesson_hypothesis_id,
--   chk_lesson_technique_id)
--
-- Re-running this file is a no-op (every statement is idempotent).
-- ============================================================================
