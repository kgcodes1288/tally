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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import orchestrator as o

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


@asynccontextmanager
async def lifespan(app):
    await recover()
    yield


app = FastAPI(title="Tally", lifespan=lifespan)


class NewTask(BaseModel):
    workspace: str
    persona: str
    prompt: str = Field(min_length=3, max_length=8000)
    model: str = "claude-sonnet-5-5"
    budget_usd: float = Field(default=0.50, gt=0, le=2.0)


class Steer(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@app.get("/api/workspaces")
def workspaces():
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
async def create(t: NewTask):
    try:
        tid = o.create_task(t.workspace, t.persona, t.prompt, t.model, t.budget_usd)
    except ValueError as e:
        raise HTTPException(400, str(e))
    running[tid] = asyncio.create_task(_run(tid))
    return {"id": tid}


@app.get("/api/tasks")
def list_tasks(limit: int = 30):
    return rows("""SELECT id::text, workspace_id, persona, model, left(prompt, 200) AS prompt, status, spent_usd, budget_usd,
                          created_at, finished_at FROM tally.tasks ORDER BY created_at DESC LIMIT %s""", min(limit, 200))


def _task(task_id):
    r = rows("""SELECT t.id::text, t.workspace_id, w.name AS workspace_name, t.persona, p.title AS persona_title, t.model, t.prompt,
                       t.status, t.spent_usd, t.budget_usd, t.result, t.error, t.created_at, t.started_at, t.finished_at
                FROM tally.tasks t JOIN tally.workspaces w ON w.id=t.workspace_id JOIN tally.personas p ON p.pg_role=t.persona
                WHERE t.id::text = %s""", task_id)
    if not r:
        raise HTTPException(404, "no such task")
    return r[0]


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    t = _task(task_id)
    out = o.RUNS / task_id / "workspace/out"
    t["files"] = [{"path": str(f.relative_to(out)), "bytes": f.stat().st_size} for f in sorted(out.rglob("*")) if f.is_file()] if out.exists() else []
    return t


@app.get("/api/tasks/{task_id}/events")
async def events(task_id: str, request: Request):
    _task(task_id)
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
def steer(task_id: str, m: Steer):
    if _task(task_id)["status"] != "running":
        raise HTTPException(409, "task is not running")
    return {"message_id": o.steer(task_id, m.body)}


@app.post("/api/tasks/{task_id}/stop", status_code=202)
def stop(task_id: str):
    if _task(task_id)["status"] != "running":
        raise HTTPException(409, "task is not running")
    o.stop(task_id)
    return {"stopping": True}


@app.get("/api/tasks/{task_id}/files/{path:path}")
def file(task_id: str, path: str):
    _task(task_id)
    base = (o.RUNS / task_id / "workspace/out").resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.is_file():      # no ../ escapes
        raise HTTPException(404, "no such file")
    return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream", filename=target.name)


@app.get("/api/usage")
def usage():
    r = rows("""SELECT coalesce(sum(cost_usd),0) AS today_usd, count(DISTINCT task_id) AS tasks_today
                FROM tally.model_usage WHERE ts >= date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'""")[0]
    return {**r, "daily_cap_usd": 3.00, "running": len(running), "max_concurrent": MAX_CONCURRENT}
