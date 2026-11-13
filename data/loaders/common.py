"""Shared helpers for workspace loaders: DuckDB for shaping raw files, psycopg COPY for fast loading into Postgres."""
import io, os, re
from pathlib import Path
import duckdb, psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"; WORK.mkdir(parents=True, exist_ok=True)

def db_url():
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("TALLY_DB_URL="): return line.split("=", 1)[1]
    raise SystemExit("TALLY_DB_URL missing from .env")

def connect():
    return psycopg.connect(db_url(), autocommit=True)

PG_TYPES = {"VARCHAR": "text", "BIGINT": "bigint", "INTEGER": "integer", "DOUBLE": "double precision", "DATE": "date",
            "TIMESTAMP": "timestamp", "BOOLEAN": "boolean", "DECIMAL(20,2)": "numeric(20,2)", "DECIMAL(10,6)": "numeric(10,6)"}

def load_table(pg, con: duckdb.DuckDBPyConnection, relation_sql: str, schema: str, table: str, comment: str = ""):
    """Materialise a DuckDB query as a Postgres table (drop + create + COPY)."""
    rel = con.sql(relation_sql)
    cols = [(n, PG_TYPES.get(str(t), "text")) for n, t in zip(rel.columns, rel.types)]
    pg.execute(f'DROP TABLE IF EXISTS {schema}.{table} CASCADE')
    pg.execute(f'CREATE TABLE {schema}.{table} (' + ", ".join(f'"{n}" {t}' for n, t in cols) + ")")
    tmp = WORK / f"{schema}.{table}.csv"
    rel.write_csv(str(tmp), header=True)
    with pg.cursor() as cur, open(tmp, "rb") as f:
        with cur.copy(f'COPY {schema}.{table} FROM STDIN (FORMAT csv, HEADER true)') as cp:
            while chunk := f.read(1 << 20): cp.write(chunk)
    tmp.unlink()
    if comment: pg.execute(sql.SQL("COMMENT ON TABLE {}.{} IS {}").format(sql.Identifier(schema), sql.Identifier(table), sql.Literal(comment)))
    n = pg.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0]
    print(f"  {schema}.{table}: {n:,} rows, {len(cols)} columns", flush=True)
    return n

def secure(pg, schema: str, table: str, scope_col: str, personas: list[str]):
    """Turn on row-level security: rows are visible only if the task's persona may see their scope value."""
    pg.execute(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
    pg.execute(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
    pg.execute(f"DROP POLICY IF EXISTS scope_read ON {schema}.{table}")
    pg.execute(f'CREATE POLICY scope_read ON {schema}.{table} FOR SELECT '
               f'USING ((SELECT tally.sees_all()) OR "{scope_col}" = ANY ((SELECT tally.my_scopes())::text[]))')
    for r in personas: pg.execute(f"GRANT SELECT ON {schema}.{table} TO {r}")

def persona(pg, workspace: str, role: str, title: str, desc: str, scopes: list[str] | None):
    """Create (or refresh) a NOLOGIN persona role and its scope grants. scopes=None means all rows."""
    if not pg.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
        pg.execute(f"CREATE ROLE {role} NOLOGIN")
    pg.execute("DELETE FROM tally.role_scopes WHERE pg_role=%s", (role,))
    pg.execute("""INSERT INTO tally.personas (pg_role, workspace_id, title, description, all_scopes) VALUES (%s,%s,%s,%s,%s)
                  ON CONFLICT (pg_role) DO UPDATE SET title=EXCLUDED.title, description=EXCLUDED.description, all_scopes=EXCLUDED.all_scopes""",
               (role, workspace, title, desc, scopes is None))
    for s in scopes or []: pg.execute("INSERT INTO tally.role_scopes VALUES (%s,%s)", (role, s))
    pg.execute(f"GRANT USAGE ON SCHEMA {workspace} TO {role}")

def money_cols(cols):
    return [c for c in cols if re.search(r"(amount|obligat|outlay|ussgl|balance|resources|authority|appropriated|recoveries)", c, re.I)
            and not re.search(r"(code|name|date|key|fiscal_year)$", c, re.I)]
