-- Platform metadata: workspaces, personas (roles) and their data scopes.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS tally;

CREATE TABLE tally.workspaces (
  id          text PRIMARY KEY,            -- also the Postgres schema name, e.g. ws_federal
  name        text NOT NULL,
  description text NOT NULL,
  scope_label text NOT NULL,               -- what a scope value means here: agency, state, borough
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- A persona is a Postgres role (NOLOGIN). Tasks get a temporary LOGIN role that inherits it.
CREATE TABLE tally.personas (
  pg_role      text PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES tally.workspaces(id),
  title        text NOT NULL,
  description  text NOT NULL,
  all_scopes   boolean NOT NULL DEFAULT false   -- oversight personas see every row
);

CREATE TABLE tally.role_scopes (
  pg_role     text NOT NULL REFERENCES tally.personas(pg_role),
  scope_value text NOT NULL,
  PRIMARY KEY (pg_role, scope_value)
);

-- Row-level security helper: may the logged-in task user see rows with this scope value?
-- SECURITY DEFINER so personas can evaluate it without reading the mapping tables directly.
CREATE FUNCTION tally.can_see(scope text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = tally, pg_catalog AS $$
  SELECT EXISTS (
    SELECT 1 FROM tally.personas p
    WHERE pg_has_role(session_user, p.pg_role, 'MEMBER')  -- session_user: the task's login (current_user is the definer here)
      AND (p.all_scopes OR EXISTS (SELECT 1 FROM tally.role_scopes s WHERE s.pg_role = p.pg_role AND s.scope_value = scope))
  );
$$;
REVOKE ALL ON tally.workspaces, tally.personas, tally.role_scopes FROM PUBLIC;
GRANT USAGE ON SCHEMA tally TO PUBLIC;
GRANT EXECUTE ON FUNCTION tally.can_see(text) TO PUBLIC;

-- Fast path used by row-level security policies. Wrapped in a scalar subquery inside the policy,
-- Postgres evaluates these ONCE per query (an InitPlan) instead of once per row.
CREATE FUNCTION tally.my_scopes() RETURNS text[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = tally, pg_catalog AS $$
  SELECT coalesce(array_agg(DISTINCT s.scope_value), '{}') FROM tally.role_scopes s
  WHERE pg_has_role(session_user, s.pg_role, 'MEMBER');
$$;
CREATE FUNCTION tally.sees_all() RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = tally, pg_catalog AS $$
  SELECT EXISTS (SELECT 1 FROM tally.personas p WHERE p.all_scopes AND pg_has_role(session_user, p.pg_role, 'MEMBER'));
$$;
GRANT EXECUTE ON FUNCTION tally.my_scopes(), tally.sees_all() TO PUBLIC;
