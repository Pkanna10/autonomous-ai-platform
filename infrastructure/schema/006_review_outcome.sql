-- Migration: 006_review_outcome.sql
-- Purpose: A lesson may record the review outcome (Step 3, D35; pulled
--          forward from U11 so the outcome is storable as soon as it exists)
-- Date: 2026-10-25
-- Depends on: 003_engine.sql
--
-- Every statement is idempotent so the file can run twice on the same
-- database: the CHECK is replaced only while it does not list 'review' yet,
-- and COMMENT replaces.
--
-- Used by services/python_agents/src/autonomous_ai_agents/persistence/postgres.py
-- (save_lesson): VerdictOutcome gained 'review' for a behaviour change that
-- passed every judge and goes to engine/review-<run_id>.
--
-- Changes:
-- 1. chk_lesson_outcome lists the five VerdictOutcome values

-- ============================================================================
-- Change 1: chk_lesson_outcome lists 'review'
-- ============================================================================
-- Impact: A review verdict's lesson is stored instead of failing the CHECK
--         after the run has spent on the trial. Existing rows hold one of the
--         four older values, which stay allowed.
-- Estimated time: <1 second (validates existing rows)

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_lesson_outcome'
      AND conrelid = 'public.lessons'::regclass
      AND pg_get_constraintdef(oid) LIKE '%''review''%'
  ) THEN
    ALTER TABLE lessons DROP CONSTRAINT IF EXISTS chk_lesson_outcome;
    ALTER TABLE lessons
      ADD CONSTRAINT chk_lesson_outcome
      CHECK (outcome IN ('keep', 'reject', 'inconclusive', 'needs_approval', 'review'));
  END IF;
END
$$;

COMMENT ON CONSTRAINT chk_lesson_outcome ON lessons IS 'Valid values (VerdictOutcome): keep, reject, inconclusive, needs_approval, review';

-- ============================================================================
-- Migration Complete
-- ============================================================================
-- Total changes:
-- - 0 new tables, 0 new columns
-- - 1 DO-guarded CHECK replacement (chk_lesson_outcome)
--
-- Re-running this file is a no-op (every statement is idempotent).
-- ============================================================================
