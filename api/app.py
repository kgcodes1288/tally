"""Tally platform API.

  GET  /api/workspaces                      workspaces and their personas
  POST /api/tasks                           create a task and start it (or queue it)
  GET  /api/tasks                           recent tasks
  GET  /api/tasks/{id}                      one task, with its output files
  GET  /api/tasks/{id}/events               live event stream (server-sent events); replays history first,
                                            resumes from Last-Event-ID, so a finished task replays the same way
  POST /api/tasks/{id}/messages             steer a running task
  POST /api/tasks/{id}/stop                 stop a running task
  GET  /api/tasks/{id}/files/{path}         download an output file
  GET  /api/usage                           today's spend against the daily cap

Bound to localhost. Authentication and the public demo come in a later phase.
"""
import asyncio, json, mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import orchestrator as o
from auth import User, check_csrf, current_user

MAX_CONCURRENT = 2
slots = asyncio.Semaphore(MAX_CONCURRENT)
running: dict[str, asyncio.Task] = {}


def rows(sql, *args):
    with o.admin_db() as db:
        cur = db.execute(sql, args)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


async def recover():
    """After a restart, nothing is really running: clean up and mark interrupted tasks."""
    for t in rows("SELECT id::text, db_login FROM tally.tasks WHERE status IN ('running', 'queued')"):
        await asyncio.to_thread(o.subprocess.run, ["docker", "rm", "-f", o._container(t["id"])], capture_output=True)
        with o.admin_db() as db:
            if t["db_login"]:
                db.execute(o.sql.SQL("DROP ROLE IF EXISTS {}").format(o.sql.Identifier(t["db_login"])))
            db.execute("UPDATE tally.tasks SET status='failed', error='interrupted by a platform restart', finished_at=now(), "
                       "proxy_token_sha256=NULL WHERE id=%s", (t["id"],))
            o.event(db, t["id"], "status", {"status": "failed", "reason": "platform restart"})


RETENTION_DAYS = int(o.os.environ.get("TALLY_RETENTION_DAYS", "30"))


async def sweep_once():
    """Remove anything a task should not leave behind, and output files past the retention period."""
    active = {t["id"] for t in rows("SELECT id::text FROM tally.tasks WHERE status IN ('queued','running')")}
    ps = await asyncio.to_thread(o.subprocess.run, ["docker", "ps", "-a", "--filter", "label=tally.task",
                                 "--format", '{{.Names}} {{.Label "tally.task"}}'], capture_output=True, text=True)
    removed = 0
    for line in ps.stdout.splitlines():
        name, task = (line.split() + [""])[:2]
        if task not in active:
            await asyncio.to_thread(o.subprocess.run, ["docker", "rm", "-f", name], capture_output=True); removed += 1
    with o.admin_db() as db:
        # only the orchestrator's own naming pattern (t_ + 12 hex), never anything else
        stale = [r for (r,) in db.execute(r"""SELECT rolname FROM pg_roles WHERE rolname ~ '^t_[0-9a-f]{12}$'
                   AND rolname NOT IN (SELECT db_login FROM tally.tasks WHERE status IN ('queued','running') AND db_login IS NOT NULL)""")]
        for r in stale:
            db.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = %s", (r,))
            db.execute(o.sql.SQL("DROP ROLE IF EXISTS {}").format(o.sql.Identifier(r)))
    expired = 0
    for t in rows("SELECT id::text FROM tally.tasks WHERE finished_at < now() - make_interval(days => %s) AND showcase_title IS NULL", RETENTION_DAYS):
        d = o.RUNS / t["id"]
        if d.exists():
            await asyncio.to_thread(o.shutil.rmtree, d, True); expired += 1
    if removed or stale or expired:
        print(f"sweep: removed {removed} containers, {len(stale)} logins, {expired} expired run folders", flush=True)
    return {"containers": removed, "logins": len(stale), "run_folders": expired}


async def sweeper():
    while True:
        try:
            await sweep_once()
        except Exception as e:                       # never let housekeeping take the API down
            print(f"sweep failed: {e}", flush=True)
        await asyncio.sleep(600)


PRIMARY_LOCK = 774201   # Postgres advisory lock id: only one API instance may recover and sweep


@asynccontextmanager
async def lifespan(app):
    # Recovery assumes "nothing is really running", which is only true for the single primary instance.
    # A second instance (a dev copy, a rolling restart) must never kill the primary's live tasks,
    # so it serves requests but skips recovery and housekeeping. The lock is held for the life of the process.
    lock = o.admin_db()
    primary = lock.execute("SELECT pg_try_advisory_lock(%s)", (PRIMARY_LOCK,)).fetchone()[0]
    task = None
    if primary:
        await recover()
        task = asyncio.create_task(sweeper())
    else:
        print("secondary API instance: skipping restart recovery and housekeeping", flush=True)
    yield
    if task:
        task.cancel()
    lock.close()


app = FastAPI(title="Tally", lifespan=lifespan, dependencies=[Depends(check_csrf)])


class NewTask(BaseModel):
    workspace: str
    persona: str
    prompt: str = Field(min_length=3, max_length=8000)
    model: str = "claude-sonnet-5-5"
    budget_usd: float = Field(default=0.50, gt=0, le=2.0)


class Steer(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@app.get("/api/me")
def me(user: User = Depends(current_user)):
    return {"email": user.email, "role": user.role, "limits": user.limits}


@app.get("/api/workspaces")
def workspaces(user: User = Depends(current_user)):
    ws = rows("SELECT id, name, description, scope_label FROM tally.workspaces ORDER BY name")
    personas = rows("""SELECT p.pg_role AS id, p.workspace_id, p.title, p.description, p.all_scopes,
                              array_remove(array_agg(s.scope_value ORDER BY s.scope_value), NULL) AS scopes
                       FROM tally.personas p LEFT JOIN tally.role_scopes s USING (pg_role) GROUP BY 1,2,3,4,5 ORDER BY p.all_scopes, p.title""")
    for w in ws:
        w["personas"] = [p for p in personas if p["workspace_id"] == w["id"]]
    return ws


async def _run(task_id):
    async with slots:                                  # at most MAX_CONCURRENT sandboxes at once
        try:
            await o.run_task(task_id)
        finally:
            running.pop(task_id, None)


@app.post("/api/tasks", status_code=201)
async def create(t: NewTask, user: User = Depends(current_user)):
    lim = user.limits
    if t.budget_usd > lim["max_budget"]:
        raise HTTPException(400, f"The budget for one task can be at most ${lim['max_budget']:.2f}")
    mine = rows("""SELECT count(*) FILTER (WHERE status IN ('queued','running')) AS active,
                          count(*) FILTER (WHERE created_at > now() - interval '1 day') AS today,
                          coalesce(sum(spent_usd) FILTER (WHERE created_at > now() - interval '1 day'), 0) AS spent
                   FROM tally.tasks WHERE created_by = %s""", user.email)[0]
    if mine["active"] >= lim["concurrent"]:
        raise HTTPException(429, "You already have a task running. Wait for it to finish or stop it.")
    if mine["today"] >= lim["tasks_per_day"]:
        raise HTTPException(429, f"Daily limit of {lim['tasks_per_day']} tasks reached. Try again tomorrow.")
    if float(mine["spent"]) >= lim["usd_per_day"]:
        raise HTTPException(429, f"Daily spending limit of ${lim['usd_per_day']:.2f} reached. Try again tomorrow.")
    try:
        tid = o.create_task(t.workspace, t.persona, t.prompt, t.model, t.budget_usd, created_by=user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    running[tid] = asyncio.create_task(_run(tid))
    return {"id": tid}


@app.get("/api/tasks")
def list_tasks(limit: int = 30, user: User = Depends(current_user)):
    return rows("""SELECT id::text, workspace_id, persona, model, left(prompt, 200) AS prompt, status, spent_usd, budget_usd,
                          created_at, finished_at FROM tally.tasks WHERE %s OR created_by = %s
                   ORDER BY created_at DESC LIMIT %s""", user.role == "owner", user.email, min(limit, 200))


def _task(task_id, user: User):
    r = rows("""SELECT t.id::text, t.created_by, t.workspace_id, w.name AS workspace_name, t.persona, p.title AS persona_title, t.model, t.prompt,
                       t.status, t.spent_usd, t.budget_usd, t.result, t.error, t.created_at, t.started_at, t.finished_at
                FROM tally.tasks t JOIN tally.workspaces w ON w.id=t.workspace_id JOIN tally.personas p ON p.pg_role=t.persona
                WHERE t.id::text = %s""", task_id)
    if not r or not user.can_see(r[0]["created_by"]):        # someone else's task looks exactly like a missing one
        raise HTTPException(404, "no such task")
    return r[0]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: User = Depends(current_user)):
    t = _task(task_id, user)
    out = o.RUNS / task_id / "workspace/out"
    t["files"] = [{"path": str(f.relative_to(out)), "bytes": f.stat().st_size} for f in sorted(out.rglob("*")) if f.is_file()] if out.exists() else []
    t["files_expired"] = t["finished_at"] is not None and not (o.RUNS / task_id).exists()
    return t


@app.get("/api/tasks/{task_id}/events")
async def events(task_id: str, request: Request, user: User = Depends(current_user)):
    _task(task_id, user)
    last = int(request.headers.get("last-event-id") or 0)

    async def stream():
        nonlocal last
        idle = 0
        while not await request.is_disconnected():
            new = rows("SELECT id, kind, data, ts FROM tally.task_events WHERE task_id::text=%s AND id>%s ORDER BY id LIMIT 500", task_id, last)
            for e in new:
                last = e["id"]
                yield f"id: {e['id']}\nevent: {e['kind']}\ndata: {json.dumps({**e['data'], 'ts': e['ts'].isoformat()}, default=str)}\n\n"
            if new:
                idle = 0
                continue
            status = rows("SELECT status FROM tally.tasks WHERE id::text=%s", task_id)[0]["status"]
            if status not in ("queued", "running"):
                yield "event: end\ndata: {}\n\n"
                return
            idle += 1
            if idle % 30 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.4)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/tasks/{task_id}/messages", status_code=202)
def steer(task_id: str, m: Steer, user: User = Depends(current_user)):
    if _task(task_id, user)["status"] != "running":
        raise HTTPException(409, "task is not running")
    return {"message_id": o.steer(task_id, m.body)}


@app.post("/api/tasks/{task_id}/stop", status_code=202)
def stop(task_id: str, user: User = Depends(current_user)):
    if _task(task_id, user)["status"] != "running":
        raise HTTPException(409, "task is not running")
    o.stop(task_id)
    return {"stopping": True}


@app.get("/api/tasks/{task_id}/files/{path:path}")
def file(task_id: str, path: str, user: User = Depends(current_user)):
    _task(task_id, user)
    return _serve_file(task_id, path)


def _serve_file(task_id: str, path: str):
    base = (o.RUNS / task_id / "workspace/out").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():      # no ../ escapes
        raise HTTPException(404, "no such file")
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"}
    if target.suffix.lower() in (".html", ".htm", ".svg"):
        # Agent-written pages are untrusted: run them in an opaque origin even when opened directly in a tab,
        # so their scripts can never reach the app, its cookies or this API.
        headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups; default-src 'self' 'unsafe-inline' data: blob:"
    inline = target.suffix.lower() in (".html", ".htm", ".pdf", ".csv", ".md", ".json", ".txt", ".svg", ".png")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                        filename=target.name, content_disposition_type="inline" if inline else "attachment", headers=headers)


# ---------------------------------------------------------------- public replays (no login; read-only; showcase tasks only)
# Cloudflare Access bypasses /demo and /api/public/ for these, so nothing here may depend on who is calling,
# and nothing here can start, steer or stop a task.

def _showcase(task_id: str):
    r = rows("""SELECT t.id::text, t.showcase_title AS title, t.showcase_blurb AS blurb, t.workspace_id, w.name AS workspace_name,
                       p.title AS persona_title, t.model, t.prompt, t.status, t.spent_usd, t.result, t.started_at, t.finished_at,
                       extract(epoch FROM t.finished_at - t.started_at)::int AS seconds
                FROM tally.tasks t JOIN tally.workspaces w ON w.id = t.workspace_id JOIN tally.personas p ON p.pg_role = t.persona
                WHERE t.id::text = %s AND t.showcase_title IS NOT NULL AND t.status IN ('succeeded', 'stopped')""", task_id)
    if not r:
        raise HTTPException(404, "not found")
    return r[0]


@app.get("/api/public/replays")
def public_replays():
    return rows("""SELECT t.id::text, t.showcase_title AS title, t.showcase_blurb AS blurb, w.name AS workspace_name, p.title AS persona_title,
                          t.model, t.spent_usd, extract(epoch FROM t.finished_at - t.started_at)::int AS seconds
                   FROM tally.tasks t JOIN tally.workspaces w ON w.id = t.workspace_id JOIN tally.personas p ON p.pg_role = t.persona
                   WHERE t.showcase_title IS NOT NULL AND t.status IN ('succeeded', 'stopped')
                   ORDER BY t.showcase_order NULLS LAST, t.finished_at DESC""")


@app.get("/api/public/replays/{task_id}")
def public_replay(task_id: str):
    t = _showcase(task_id)
    out = o.RUNS / task_id / "workspace/out"
    t["files"] = [{"path": str(f.relative_to(out)), "bytes": f.stat().st_size} for f in sorted(out.rglob("*")) if f.is_file()] if out.exists() else []
    t["events"] = rows("SELECT id, kind, data, ts FROM tally.task_events WHERE task_id::text = %s AND kind <> 'log' ORDER BY id", task_id)
    for e in t["events"]:
        e["data"] = {**e["data"], "ts": e.pop("ts").isoformat()}
    return t


@app.get("/api/public/replays/{task_id}/files/{path:path}")
def public_file(task_id: str, path: str):
    _showcase(task_id)
    return _serve_file(task_id, path)


@app.get("/api/usage")
def usage(user: User = Depends(current_user)):
    r = rows("""SELECT coalesce(sum(cost_usd),0) AS today_usd, count(DISTINCT task_id) AS tasks_today
                FROM tally.model_usage WHERE ts >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""")[0]
    return {**r, "daily_cap_usd": 3.00, "running": len(running), "max_concurrent": MAX_CONCURRENT}


# ---------------------------------------------------------------- web app (built by `npm run build` in web/)
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    if not request.url.path.startswith("/api/tasks/") or "/files/" not in request.url.path:
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return resp


if WEB.exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):                       # unknown API paths are errors, not the app shell
            raise HTTPException(404, "not found")
        f = (WEB / path).resolve()
        if path and WEB in f.parents and f.is_file():
            return FileResponse(f)
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})
