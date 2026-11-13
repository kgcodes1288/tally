-- Knowledge base: chunks of docs, glossaries and playbooks per workspace, searchable by meaning and by keyword.
CREATE FUNCTION tally.my_workspaces() RETURNS text[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = tally, pg_catalog AS $$
  SELECT coalesce(array_agg(DISTINCT p.workspace_id), '{}') FROM tally.personas p WHERE pg_has_role(session_user, p.pg_role, 'MEMBER');
$$;
GRANT EXECUTE ON FUNCTION tally.my_workspaces() TO PUBLIC;

CREATE TABLE tally.kb_chunks (
  id           bigserial PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES tally.workspaces(id),
  doc          text NOT NULL,             -- document or source name
  section      text NOT NULL,             -- heading or term
  source_url   text,
  content      text NOT NULL,
  embedding    vector(384) NOT NULL,      -- BAAI/bge-small-en-v1.5, computed locally with fastembed
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', section || ' ' || content)) STORED
);
CREATE INDEX ON tally.kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON tally.kb_chunks USING gin (tsv);
CREATE INDEX ON tally.kb_chunks (workspace_id);
ALTER TABLE tally.kb_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally.kb_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY ws_read ON tally.kb_chunks FOR SELECT USING (workspace_id = ANY ((SELECT tally.my_workspaces())::text[]));
GRANT SELECT ON tally.kb_chunks TO PUBLIC;

-- Hybrid search with reciprocal rank fusion: rank by vector similarity and by keyword match, then merge.
-- SECURITY INVOKER (default), so row-level security above still applies to whoever calls it.
CREATE FUNCTION tally.kb_search(q_embedding vector, q_text text, k int DEFAULT 6)
RETURNS TABLE (id bigint, workspace_id text, doc text, section text, content text, source_url text, score double precision)
LANGUAGE sql STABLE AS $$
  WITH v AS (SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> q_embedding) AS r FROM tally.kb_chunks c ORDER BY c.embedding <=> q_embedding LIMIT 40),
       t AS (SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', q_text)) DESC) AS r
             FROM tally.kb_chunks c WHERE c.tsv @@ websearch_to_tsquery('english', q_text) LIMIT 40),
       f AS (SELECT id, sum(1.0 / (60 + r)) AS score FROM (SELECT * FROM v UNION ALL SELECT * FROM t) u GROUP BY id)
  SELECT c.id, c.workspace_id, c.doc, c.section, c.content, c.source_url, f.score
  FROM f JOIN tally.kb_chunks c USING (id) ORDER BY f.score DESC LIMIT k;
$$;
GRANT EXECUTE ON FUNCTION tally.kb_search(vector, text, int) TO PUBLIC;
