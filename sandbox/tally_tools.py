"""Tally's data tools, served to the agent as an in-process MCP server.

These are the ONLY ways the agent can reach workspace data. They connect with the task's temporary,
role-scoped database login, so row-level security decides what is visible; the tools add read-only
transactions, statement timeouts and result limits on top.
"""
import csv, json, os, re
from pathlib import Path
from typing import Any

import psycopg
from claude_agent_sdk import ToolAnnotations, create_sdk_mcp_server, tool

DSN = os.environ["TALLY_DB_DSN"]
WORKSPACE = os.environ["TALLY_WORKSPACE"]          # also the schema name, e.g. ws_federal
DATA_DIR = Path("/workspace/data"); DATA_DIR.mkdir(parents=True, exist_ok=True)
MAX_ROWS_SHOWN = 200
EXPORT_ROW_LIMIT = 2_000_000
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_embedder = None


def _conn():
    c = psycopg.connect(DSN, autocommit=True, connect_timeout=10)
    c.execute("SET default_transaction_read_only = on")
    c.execute("SET statement_timeout = '90s'")
    c.execute(f"SET search_path = {WORKSPACE}, tally, public")   # public holds the pgvector type
    return c


def _text(s: str, error: bool = False) -> dict[str, Any]:
    out = {"content": [{"type": "text", "text": s}]}
    if error: out["is_error"] = True
    return out


def _table(cols, rows, total=None) -> str:
    """Render rows as a compact pipe table the model reads easily."""
    fmt = lambda v: "" if v is None else str(v).replace("|", "/").replace("\n", " ")[:120]
    lines = [" | ".join(cols), " | ".join("---" for _ in cols)] + [" | ".join(fmt(v) for v in r) for r in rows]
    if total is not None and total > len(rows):
        lines.append(f"... showing {len(rows)} of {total} rows. Use export_query to get everything as a CSV file.")
    return "\n".join(lines)


@tool("whoami", "Who you are acting for in this task: workspace, persona, which rows they may see, and the rules of this sandbox.", {}, annotations=READ_ONLY)
async def whoami(args):
    return _text(json.dumps({
        "workspace": WORKSPACE, "workspace_name": os.environ.get("TALLY_WORKSPACE_NAME"),
        "persona": os.environ.get("TALLY_PERSONA_TITLE"), "visible_scope": os.environ.get("TALLY_SCOPE_DESC"),
        "rules": ["Data access is read-only and limited by the database to this persona's rows.",
                  "Save deliverables (CSV, HTML, PDF) to /workspace/out. Use /workspace/data for working files.",
                  "There is no internet access from this sandbox."]}, indent=2))


@tool("list_tables", "List the tables you can query in this workspace, with their descriptions and approximate row counts.", {}, annotations=READ_ONLY)
async def list_tables(args):
    with _conn() as c:
        rows = c.execute("""
            SELECT t.table_name, coalesce(obj_description(format('%%I.%%I', t.table_schema, t.table_name)::regclass), ''),
                   coalesce((SELECT reltuples::bigint FROM pg_class WHERE oid = format('%%I.%%I', t.table_schema, t.table_name)::regclass), 0)
            FROM information_schema.tables t
            WHERE t.table_schema = %s AND has_table_privilege(format('%%I.%%I', t.table_schema, t.table_name), 'SELECT')
            ORDER BY 1""", (WORKSPACE,)).fetchall()
    return _text(_table(["table", "description", "approx_rows (all scopes)"], rows))


@tool("describe_table", "Show a table's columns, types and descriptions, plus 5 sample rows you are allowed to see.",
      {"table": str}, annotations=READ_ONLY)
async def describe_table(args):
    name = args["table"].split(".")[-1]
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        return _text("Invalid table name.", error=True)
    try:
        with _conn() as c:
            cols = c.execute("""SELECT column_name, data_type, coalesce(col_description(format('%%I.%%I', table_schema, table_name)::regclass, ordinal_position), '')
                                FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""",
                             (WORKSPACE, name)).fetchall()
            if not cols:
                return _text(f"No table named {name} in this workspace.", error=True)
            cur = c.execute(f'SELECT * FROM "{name}" LIMIT 5')
            sample = _table([d.name for d in cur.description], cur.fetchall())
    except psycopg.Error as e:
        return _text(f"Could not describe {name}: {e.diag.message_primary or e}", error=True)
    return _text(_table(["column", "type", "description"], cols) + "\n\nSample rows:\n" + sample)


@tool("run_sql", "Run one read-only SQL query (PostgreSQL) against this workspace and see up to 200 rows. "
      "Aggregate in SQL where you can. Tables are in the workspace schema, so unqualified names work.",
      {"sql": str}, annotations=READ_ONLY)
async def run_sql(args):
    sql = args["sql"].strip().rstrip(";")
    try:
        with _conn() as c:
            cur = c.execute(sql)
            if cur.description is None:
                return _text("Query ran but returned no rows.")
            rows = cur.fetchmany(MAX_ROWS_SHOWN + 1)
            total = len(rows) if len(rows) <= MAX_ROWS_SHOWN else f"more than {MAX_ROWS_SHOWN}"
            shown = rows[:MAX_ROWS_SHOWN]
            text = _table([d.name for d in cur.description], shown)
            if len(rows) > MAX_ROWS_SHOWN:
                text += f"\n... showing the first {MAX_ROWS_SHOWN} rows ({total}). Aggregate further, or use export_query for the full result."
            return _text(text)
    except psycopg.Error as e:
        msg = e.diag.message_primary or str(e)
        hint = " This persona is not allowed to do that." if isinstance(e, psycopg.errors.InsufficientPrivilege) else ""
        return _text(f"SQL error: {msg}.{hint}", error=True)


@tool("export_query", "Run a read-only SQL query and save the full result as a CSV file under /workspace/data, for analysis with "
      "pandas or DuckDB via Bash, or for delivery. Returns the file path, row count and columns.",
      {"sql": str, "filename": str}, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False))
async def export_query(args):
    fname = re.sub(r"[^A-Za-z0-9_.-]", "_", args["filename"]) or "export.csv"
    if not fname.endswith(".csv"): fname += ".csv"
    path = DATA_DIR / fname
    try:
        with _conn() as c, open(path, "w", newline="") as f:
            cur = c.execute(args["sql"].strip().rstrip(";"))
            w = csv.writer(f); cols = [d.name for d in cur.description]; w.writerow(cols); n = 0
            while batch := cur.fetchmany(10_000):
                w.writerows(batch); n += len(batch)
                if n >= EXPORT_ROW_LIMIT:
                    break
    except psycopg.Error as e:
        return _text(f"SQL error: {e.diag.message_primary or e}", error=True)
    capped = " (stopped at the 2,000,000 row limit)" if n >= EXPORT_ROW_LIMIT else ""
    return _text(f"Saved {n:,} rows{capped} to {path}\nColumns: {', '.join(cols)}")


@tool("search_knowledge", "Search this workspace's knowledge base (official documents, data dictionaries, playbooks, uploads). "
      "Returns passages with a citation and an authority level. Check it before deciding how to define a metric or run a reconciliation, "
      "and cite what you use.", {"query": str}, annotations=READ_ONLY)
async def search_knowledge(args):
    global _embedder
    if _embedder is None:
        from fastembed import TextEmbedding
        _embedder = TextEmbedding("BAAI/bge-small-en-v1.5")
    q = args["query"]
    vec = "[" + ",".join(f"{x:.6f}" for x in next(iter(_embedder.embed([q])))) + "]"
    with _conn() as c:
        hits = c.execute("SELECT citation, authority, content FROM tally.kb_search(%s::vector, %s, 6)", (vec, q)).fetchall()
    if not hits:
        return _text("No matching knowledge found.")
    return _text("\n\n".join(f"[{i}] {cit} (authority: {auth})\n{content[:1500]}" for i, (cit, auth, content) in enumerate(hits, 1)))


TOOLS = [whoami, list_tables, describe_table, run_sql, export_query, search_knowledge]
server = create_sdk_mcp_server(name="tally", version="1.0.0", tools=TOOLS)
TOOL_NAMES = [f"mcp__tally__{t.name}" for t in TOOLS]
