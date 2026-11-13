-- Tasks, their event log (the single source for live progress, replays and audits) and model usage/cost.
CREATE TABLE tally.tasks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workspace_id  text NOT NULL REFERENCES tally.workspaces(id),
  persona       text NOT NULL REFERENCES tally.personas(pg_role),
  model         text NOT NULL,
  prompt        text NOT NULL,
  status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','stopped','budget_exceeded')),
  budget_usd    numeric(8,4) NOT NULL DEFAULT 0.50,
  spent_usd     numeric(10,6) NOT NULL DEFAULT 0,
  proxy_token_sha256 text UNIQUE,          -- the sandbox holds the token; we keep only its hash
  db_login      text,                      -- temporary LOGIN role for this task (dropped when the task ends)
  container_id  text,
  result        text,                      -- final answer text
  error         text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  started_at    timestamptz,
  finished_at   timestamptz
);
CREATE INDEX ON tally.tasks (created_at DESC);

CREATE TABLE tally.task_events (
  id       bigserial PRIMARY KEY,
  task_id  uuid NOT NULL REFERENCES tally.tasks(id) ON DELETE CASCADE,
  ts       timestamptz NOT NULL DEFAULT clock_timestamp(),
  kind     text NOT NULL,                 -- status, text, thinking, tool_call, tool_result, steer_queued, steer_delivered, usage, artifact, error, result
  data     jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX ON tally.task_events (task_id, id);

CREATE TABLE tally.model_usage (
  id                 bigserial PRIMARY KEY,
  task_id            uuid NOT NULL REFERENCES tally.tasks(id) ON DELETE CASCADE,
  ts                 timestamptz NOT NULL DEFAULT now(),
  model              text NOT NULL,
  input_tokens       int NOT NULL DEFAULT 0,
  output_tokens      int NOT NULL DEFAULT 0,
  cache_read_tokens  int NOT NULL DEFAULT 0,
  cache_write_tokens int NOT NULL DEFAULT 0,
  cost_usd           numeric(10,6) NOT NULL
);
CREATE INDEX ON tally.model_usage (ts);

-- Steering messages typed while a task runs. Delivered to the agent at its next tool result.
CREATE TABLE tally.task_messages (
  id           bigserial PRIMARY KEY,
  task_id      uuid NOT NULL REFERENCES tally.tasks(id) ON DELETE CASCADE,
  body         text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  delivered_at timestamptz
);

-- Service roles: the proxy may only read tasks and record usage; it never sees workspace data.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tally_proxy') THEN CREATE ROLE tally_proxy LOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA tally TO tally_proxy;
GRANT SELECT, UPDATE (spent_usd, status) ON tally.tasks TO tally_proxy;
GRANT INSERT ON tally.model_usage, tally.task_events TO tally_proxy;
GRANT SELECT (cost_usd, ts) ON tally.model_usage TO tally_proxy;   -- for the daily cap
GRANT USAGE ON SEQUENCE tally.model_usage_id_seq, tally.task_events_id_seq TO tally_proxy;

-- Who ran each task (email from the Cloudflare Access login, or owner@local for local access).
ALTER TABLE tally.tasks ADD COLUMN IF NOT EXISTS created_by text NOT NULL DEFAULT 'owner@local';
CREATE INDEX IF NOT EXISTS tasks_created_by ON tally.tasks (created_by, created_at DESC);

-- Public replay gallery: only tasks the owner gives a showcase title appear at /demo (read-only, no login).
ALTER TABLE tally.tasks ADD COLUMN IF NOT EXISTS showcase_title text;
ALTER TABLE tally.tasks ADD COLUMN IF NOT EXISTS showcase_blurb text;
ALTER TABLE tally.tasks ADD COLUMN IF NOT EXISTS showcase_order int;
