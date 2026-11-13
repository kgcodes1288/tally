-- Knowledge base: documents (PDFs, web pages, wiki articles, playbooks, uploads) split into passages,
-- searchable by meaning and keyword, with a citation for every passage.

CREATE FUNCTION tally.my_workspaces() RETURNS text[]
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = tally, pg_catalog AS $$
  SELECT coalesce(array_agg(DISTINCT p.workspace_id), '{}') FROM tally.personas p WHERE pg_has_role(session_user, p.pg_role, 'MEMBER');
$$;
GRANT EXECUTE ON FUNCTION tally.my_workspaces() TO PUBLIC;

CREATE TABLE tally.kb_documents (
  id           bigserial PRIMARY KEY,
  workspace_id text NOT NULL REFERENCES tally.workspaces(id),
  title        text NOT NULL,
  source_type  text NOT NULL CHECK (source_type IN ('pdf', 'html', 'wiki', 'markdown', 'docx', 'glossary', 'metadata')),
  authority    text NOT NULL CHECK (authority IN ('official', 'internal', 'reference', 'uploaded')),
  publisher    text,
  url          text,
  sha256       text NOT NULL,             -- of the raw source, to skip unchanged documents
  pages        int,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workspace_id, title)
);

CREATE TABLE tally.kb_chunks (
  id           bigserial PRIMARY KEY,
  doc_id       bigint NOT NULL REFERENCES tally.kb_documents(id) ON DELETE CASCADE,
  workspace_id text NOT NULL,
  section      text NOT NULL,             -- heading, glossary term or "Page N"
  page         int,                       -- PDF page number (1-based), null otherwise
  content      text NOT NULL,
  citation     text NOT NULL,             -- ready to show, e.g. "Mayor's Management Report, Fiscal 2025, p. 212"
  embedding    vector(384) NOT NULL,      -- BAAI/bge-small-en-v1.5 via fastembed, computed locally
  tsv          tsvector GENERATED ALWAYS AS (to_tsvector('english', section || ' ' || content)) STORED
);
CREATE INDEX ON tally.kb_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX ON tally.kb_chunks USING gin (tsv);
CREATE INDEX ON tally.kb_chunks (workspace_id);

ALTER TABLE tally.kb_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally.kb_documents FORCE ROW LEVEL SECURITY;
CREATE POLICY ws_read ON tally.kb_documents FOR SELECT USING (workspace_id = ANY ((SELECT tally.my_workspaces())::text[]));
ALTER TABLE tally.kb_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE tally.kb_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY ws_read ON tally.kb_chunks FOR SELECT USING (workspace_id = ANY ((SELECT tally.my_workspaces())::text[]));
GRANT SELECT ON tally.kb_documents, tally.kb_chunks TO PUBLIC;

-- Hybrid search: reciprocal rank fusion of vector similarity and keyword rank, with a small boost for authoritative sources.
-- SECURITY INVOKER (the default), so row-level security applies to whoever calls it.
CREATE FUNCTION tally.kb_search(q_embedding vector, q_text text, k int DEFAULT 6)
RETURNS TABLE (chunk_id bigint, workspace_id text, title text, section text, page int, authority text,
               citation text, url text, content text, score double precision)
LANGUAGE sql STABLE AS $$
  WITH v AS (SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> q_embedding) AS r
             FROM tally.kb_chunks c ORDER BY c.embedding <=> q_embedding LIMIT 50),
       t AS (SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery('english', q_text)) DESC) AS r
             FROM tally.kb_chunks c WHERE c.tsv @@ websearch_to_tsquery('english', q_text) LIMIT 50),
       f AS (SELECT id, sum(1.0 / (60 + r)) AS s FROM (SELECT * FROM v UNION ALL SELECT * FROM t) u GROUP BY id)
  SELECT chunk_id, workspace_id, title, section, page, authority, citation, url, content, score FROM (
    SELECT c.id AS chunk_id, c.workspace_id, d.title, c.section, c.page, d.authority, c.citation, d.url, c.content,
           f.s * CASE d.authority WHEN 'official' THEN 1.15 WHEN 'internal' THEN 1.10 WHEN 'uploaded' THEN 1.05 ELSE 1.0 END AS score,
           row_number() OVER (PARTITION BY c.doc_id ORDER BY f.s DESC) AS per_doc   -- at most 2 passages per document
    FROM f JOIN tally.kb_chunks c ON c.id = f.id JOIN tally.kb_documents d ON d.id = c.doc_id) ranked
  WHERE per_doc <= 2
  ORDER BY score DESC LIMIT k;
$$;
GRANT EXECUTE ON FUNCTION tally.kb_search(vector, text, int) TO PUBLIC;
