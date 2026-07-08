-- SmartHealth — Planning digest recipient email
-- Run after 001_core.sql.
--
-- The daily planning digest (tasks/planning_tasks.run_daily_planning_digest)
-- emails each district/state admin their scope's pre-emptive refill list. Users
-- were keyed only by phone (WhatsApp auth); add an optional email so the digest
-- has somewhere to send. WhatsApp delivery is a later step.

ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(200);
