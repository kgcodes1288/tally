"""Tally model proxy: the only component that holds the Anthropic API key.

Sandboxes call this proxy instead of api.anthropic.com, presenting a per-task token. The proxy
  1. resolves the token to a running task (only a hash of the token is stored),
  2. refuses the call if the task budget or the daily cap is used up, or if the model or path is not allowed,
  3. forwards the call with the real key, streaming the response back unchanged,
  4. reads token usage from the response and records the cost against the task.
"""
import hashlib, json, os
from datetime import datetime, timezone
from decimal import Decimal

import httpx, psycopg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

UPSTREAM = "https://api.anthropic.com"
API_KEY = open(os.environ.get("ANTHROPIC_API_KEY_FILE", "/run/secrets/anthropic_api_key")).read().strip()
DB_URL = os.environ["TALLY_PROXY_DB_URL"]
DAILY_CAP_USD = Decimal(os.environ.get("TALLY_DAILY_CAP_USD", "3.00"))
ALLOWED_PATHS = {"/v1/messages", "/v1/messages/count_tokens"}

# USD per million tokens: input, output, cache read, cache write (5-minute)
PRICES = {
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00"), Decimal("0.20"), Decimal("2.50")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00"), Decimal("0.20"), Decimal("5.00")),
    "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00"), Decimal("0.10"), Decimal("1.25")),
}

app = FastAPI(title="tally-proxy")
client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=20))


def error(status, kind, message):
    """Errors in Anthropic's own format, so the agent SDK reports them cleanly."""
    return JSONResponse({"type": "error", "error": {"type": kind, "message": message}}, status_code=status)


def cost(model, u):
    p = PRICES[model]
    return (Decimal(u.get("input_tokens", 0)) * p[0] + Decimal(u.get("output_tokens", 0)) * p[1]
            + Decimal(u.get("cache_read_input_tokens", 0)) * p[2] + Decimal(u.get("cache_creation_input_tokens", 0)) * p[3]) / Decimal(1_000_000)


def record(task_id, model, u):
    c = cost(model, u)
    with psycopg.connect(DB_URL, autocommit=True) as db:
        db.execute("""INSERT INTO tally.model_usage (task_id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd)
                      VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                   (task_id, model, u.get("input_tokens", 0), u.get("output_tokens", 0),
                    u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0), c))
        spent = db.execute("UPDATE tally.tasks SET spent_usd = spent_usd + %s WHERE id = %s RETURNING spent_usd", (c, task_id)).fetchone()[0]
        db.execute("INSERT INTO tally.task_events (task_id, kind, data) VALUES (%s, 'usage', %s)",
                   (task_id, json.dumps({"model": model, "cost_usd": float(c), "task_spent_usd": float(spent), **u})))


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.api_route("/{path:path}", methods=["POST", "GET"])
async def forward(path: str, request: Request):
    path = "/" + path
    if path not in ALLOWED_PATHS:
        return error(404, "not_found_error", f"{path} is not available through the Tally proxy")
    token = request.headers.get("x-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        return error(401, "authentication_error", "missing task token")
    with psycopg.connect(DB_URL, autocommit=True) as db:
        row = db.execute("SELECT id, status, budget_usd, spent_usd FROM tally.tasks WHERE proxy_token_sha256 = %s",
                         (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not row or row[1] != "running":
            return error(401, "authentication_error", "unknown or finished task")
        task_id, _, budget, spent = row
        if spent >= budget:
            db.execute("UPDATE tally.tasks SET status = 'budget_exceeded' WHERE id = %s", (task_id,))
            return error(403, "permission_error", f"Task budget of ${budget} is used up. Stop and report what you have so far.")
        today = datetime.now(timezone.utc).date()
        day_total = db.execute("SELECT coalesce(sum(cost_usd), 0) FROM tally.model_usage WHERE ts >= %s", (today,)).fetchone()[0]
        if day_total >= DAILY_CAP_USD:
            return error(403, "permission_error", "Tally's daily spending cap is reached. Try again tomorrow.")

    body = await request.body()
    payload = json.loads(body) if body else {}
    model = payload.get("model", "")
    if model not in PRICES:
        return error(400, "invalid_request_error", f"model {model!r} is not allowed here; use one of {sorted(PRICES)}")

    headers = {k: v for k, v in request.headers.items()
               if k.lower() in ("content-type", "anthropic-version", "anthropic-beta", "accept")}
    headers["x-api-key"] = API_KEY
    headers["accept-encoding"] = "identity"   # uncompressed, so the stream can be relayed and its usage read as-is
    upstream = client.build_request(request.method, UPSTREAM + path, headers=headers, content=body, params=request.query_params)
    resp = await client.send(upstream, stream=True)

    if path != "/v1/messages":                    # token counting: no charge, pass through
        data = await resp.aread(); await resp.aclose()
        return StreamingResponse(iter([data]), status_code=resp.status_code, media_type=resp.headers.get("content-type"))

    async def relay():
        usage, buf, is_sse = {}, b"", "text/event-stream" in resp.headers.get("content-type", "")
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
                buf += chunk
                if is_sse:
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        if line.startswith(b"data:"):
                            try:
                                ev = json.loads(line[5:])
                            except ValueError:
                                continue
                            if ev.get("type") == "message_start":
                                usage.update(ev["message"].get("usage") or {})
                            elif ev.get("type") == "message_delta" and ev.get("usage"):
                                usage.update({k: v for k, v in ev["usage"].items() if v is not None})
            if not is_sse and resp.status_code == 200:
                usage = json.loads(buf).get("usage") or {}
        finally:
            await resp.aclose()
            if usage:
                record(task_id, model, {k: v for k, v in usage.items() if isinstance(v, int)})

    passthrough = {k: v for k, v in resp.headers.items() if k.lower() in ("content-type", "request-id", "anthropic-ratelimit-requests-remaining")}
    return StreamingResponse(relay(), status_code=resp.status_code, headers=passthrough)
