"""Task orchestrator: runs each Tally task in its own gVisor sandbox and records everything it does.

Lifecycle of a task:
  create  -> row in tally.tasks (queued)
  start   -> temporary database login that inherits only the persona (expires in 1 hour), single-use proxy token
             (only its hash is stored), run folder, sandbox container with hard limits
  run     -> every JSON line the sandbox prints becomes a row in tally.task_events
  steer   -> a message file in the task inbox; the agent reads it at its next tool result
  stop    -> SIGUSR1 (clean interrupt), then a hard stop if needed
  finish  -> final status and answer saved, login dropped, container removed, output files kept
"""
import asyncio, hashlib, json, os, secrets, shutil, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Json

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
IMAGE = os.environ.get("TALLY_SANDBOX_IMAGE", "tally-sandbox:dev")
PROXY_URL = "http://172.30.0.11:8080"
DB_SANDBOX_HOST = "172.30.0.10"
TASK_TIMEOUT_S = int(os.environ.get("TALLY_TASK_TIMEOUT_S", "900"))
MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}


def admin_db():
    url = next(l.split("=", 1)[1] for l in (ROOT / ".env").read_text().splitlines() if l.startswith("TALLY_DB_URL="))
    return psycopg.connect(url, autocommit=True)


def event(db, task_id, kind, data):
    db.execute("INSERT INTO tally.task_events (task_id, kind, data) VALUES (%s, %s, %s)", (task_id, kind, Json(data)))


def create_task(workspace: str, persona: str, prompt: str, model: str = "claude-sonnet-5-5", budget_usd: float = 0.50) -> str:
    if model not in MODELS:
        raise ValueError(f"model must be one of {sorted(MODELS)}")
    with admin_db() as db:
        ok = db.execute("SELECT 1 FROM tally.personas WHERE pg_role=%s AND workspace_id=%s", (persona, workspace)).fetchone()
        if not ok:
            raise ValueError(f"{persona} is not a persona of {workspace}")
        tid = db.execute("INSERT INTO tally.tasks (workspace_id, persona, model, prompt, budget_usd) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                         (workspace, persona, model, prompt, budget_usd)).fetchone()[0]
        event(db, tid, "status", {"status": "queued"})
    return str(tid)


def sandbox_args(run: Path, env: dict) -> list[str]:
    """Isolation settings for every task sandbox (also used by the security tests, so they test exactly this)."""
    args = ["--runtime=runsc",                                  # gVisor: the agent never talks to the host kernel
            "--network", "tally-sandbox",                       # internal-only network: database and model proxy, no internet
            "--memory", "2g", "--cpus", "2", "--pids-limit", "512",
            "--read-only",                                      # system disk is read-only
            "--tmpfs", "/tmp:rw,size=512m", "--tmpfs", "/home/agent:rw,size=256m,uid=1000,gid=1000",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--user", "1000:1000",
            "-v", f"{run / 'workspace'}:/workspace", "-v", f"{run / 'task'}:/task"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    return args


def _container(task_id: str) -> str:
    return f"tally-task-{task_id[:8]}"


async def run_task(task_id: str, on_event=None):
    """Start the sandbox, stream its events into the database, and clean up. Returns the final status."""
    db = admin_db()
    t = db.execute("""SELECT t.workspace_id, t.persona, t.model, t.prompt, t.budget_usd, w.name, p.title, p.all_scopes,
                             coalesce(string_agg(s.scope_value, ', ' ORDER BY s.scope_value), ''), w.scope_label
                      FROM tally.tasks t JOIN tally.workspaces w ON w.id = t.workspace_id JOIN tally.personas p ON p.pg_role = t.persona
                      LEFT JOIN tally.role_scopes s ON s.pg_role = p.pg_role WHERE t.id = %s GROUP BY 1,2,3,4,5,6,7,8,10""",
                   (task_id,)).fetchone()
    ws, persona, model, prompt, budget, ws_name, title, all_scopes, scopes, scope_label = t
    scope_desc = f"all {scope_label} values" if all_scopes else f"{scope_label} in ({scopes})"

    login, pw = "t_" + secrets.token_hex(6), secrets.token_urlsafe(24)
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {} VALID UNTIL {} CONNECTION LIMIT 10").format(
        sql.Identifier(login), sql.Literal(pw), sql.Identifier(persona), sql.Literal(expires)))
    token = secrets.token_urlsafe(32)
    run = RUNS / task_id
    for d in ("workspace/out", "workspace/data", "task/inbox"):
        (run / d).mkdir(parents=True, exist_ok=True)
    (run / "task/prompt.txt").write_text(prompt)
    db.execute("UPDATE tally.tasks SET status='running', started_at=now(), db_login=%s, proxy_token_sha256=%s WHERE id=%s",
               (login, hashlib.sha256(token.encode()).hexdigest(), task_id))
    event(db, task_id, "status", {"status": "starting", "sandbox": "gVisor", "persona": title, "scope": scope_desc})

    name = _container(task_id)
    env = {"TALLY_TASK_ID": task_id, "TALLY_MODEL": model, "TALLY_WORKSPACE": ws, "TALLY_WORKSPACE_NAME": ws_name,
           "TALLY_PERSONA_TITLE": title, "TALLY_SCOPE_DESC": scope_desc, "TALLY_BUDGET_USD": str(budget),
           "TALLY_DB_DSN": f"postgresql://{login}:{pw}@{DB_SANDBOX_HOST}:5432/tally",
           "ANTHROPIC_BASE_URL": PROXY_URL, "ANTHROPIC_API_KEY": token,
           "ANTHROPIC_DEFAULT_HAIKU_MODEL": "claude-haiku-4-5", "ANTHROPIC_SMALL_FAST_MODEL": "claude-haiku-4-5"}
    await asyncio.to_thread(subprocess.run, ["docker", "run", "-d", "--name", name, "--label", f"tally.task={task_id}"]
                            + sandbox_args(run, env) + [IMAGE], check=True, capture_output=True)

    result, stopped = None, False
    logs = await asyncio.create_subprocess_exec("docker", "logs", "-f", name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)

    async def pump():
        nonlocal result
        async for raw in logs.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
                kind, data = ev["kind"], ev["data"]
            except (ValueError, KeyError):
                kind, data = "log", {"line": line[:2000]}
            event(db, task_id, kind, data)
            if on_event:
                on_event(kind, data)
            if kind == "steer_delivered":
                db.execute("UPDATE tally.task_messages SET delivered_at = now() WHERE id = %s", (data.get("message_id"),))
            if kind == "result":
                result = data

    try:
        await asyncio.wait_for(pump(), timeout=TASK_TIMEOUT_S)
    except asyncio.TimeoutError:
        event(db, task_id, "error", {"message": f"Timed out after {TASK_TIMEOUT_S} seconds"})
        await asyncio.to_thread(subprocess.run, ["docker", "kill", name], capture_output=True)
    waited = await asyncio.to_thread(subprocess.run, ["docker", "wait", name], capture_output=True, text=True)
    exit_code = int(waited.stdout.strip() or 1)

    current = db.execute("SELECT status FROM tally.tasks WHERE id=%s", (task_id,)).fetchone()[0]
    stopped = (run / "task/.stop").exists()
    if current == "budget_exceeded":
        status = "budget_exceeded"
    elif stopped:
        status = "stopped"
    elif result and not result.get("is_error") and exit_code == 0:
        status = "succeeded"
    else:
        status = "failed"
    db.execute("UPDATE tally.tasks SET status=%s, finished_at=now(), result=%s, error=%s WHERE id=%s",
               (status, (result or {}).get("text"), None if status == "succeeded" else f"exit {exit_code}", task_id))
    event(db, task_id, "status", {"status": status})

    # cleanup: no lingering credentials or containers; output files stay in runs/<task>/workspace/out
    db.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s", (login,))
    db.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))
    db.execute("UPDATE tally.tasks SET proxy_token_sha256 = NULL WHERE id=%s", (task_id,))
    await asyncio.to_thread(subprocess.run, ["docker", "rm", "-f", name], capture_output=True)
    shutil.rmtree(run / "task/inbox", ignore_errors=True)
    db.close()
    return status


def steer(task_id: str, body: str) -> int:
    """Queue a message for a running task. It is delivered at the agent's next tool result."""
    with admin_db() as db:
        mid = db.execute("INSERT INTO tally.task_messages (task_id, body) VALUES (%s,%s) RETURNING id", (task_id, body)).fetchone()[0]
        inbox = RUNS / task_id / "task/inbox"
        tmp = inbox / f".{mid}.tmp"
        tmp.write_text(json.dumps({"id": mid, "body": body}))
        tmp.rename(inbox / f"{mid:08d}.json")            # atomic: the agent never sees half a file
        event(db, task_id, "steer_queued", {"message_id": mid, "body": body})
    return mid


def stop(task_id: str):
    """Ask the agent to stop cleanly; force it after 20 seconds."""
    (RUNS / task_id / "task/.stop").touch()
    name = _container(task_id)
    subprocess.run(["docker", "kill", "--signal", "SIGUSR1", name], capture_output=True)

    async def force():
        await asyncio.sleep(20)
        subprocess.run(["docker", "stop", "-t", "5", name], capture_output=True)
    try:
        return asyncio.get_running_loop().create_task(force())   # runs in the background; the caller need not await it
    except RuntimeError:                                          # called outside an event loop: interrupt only
        return None
