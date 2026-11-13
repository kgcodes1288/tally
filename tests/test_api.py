"""API access rules: who is calling, what they may see, and the limits that apply. No model calls."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import app as tally          # noqa: E402
from auth import User, current_user  # noqa: E402

H = {"x-tally-request": "1"}


@pytest.fixture
def client():
    tally.app.dependency_overrides.clear()
    yield TestClient(tally.app)              # no `with`: the lifespan (restart recovery, sweeper) does not run
    tally.app.dependency_overrides.clear()


def as_user(email, role):
    tally.app.dependency_overrides[current_user] = lambda: User(email, role)


def test_local_request_is_owner(client):
    assert client.get("/api/me").json()["role"] == "owner"


def test_cloudflare_request_without_access_is_refused(client):
    r = client.get("/api/me", headers={"cf-ray": "abc123-SJC", "cf-connecting-ip": "203.0.113.9"})
    assert r.status_code in (401, 503)       # 503 while Access is not configured, 401 once it is


def test_forged_access_token_is_refused(client, monkeypatch):
    import auth
    monkeypatch.setattr(auth, "CF_AUD", "test-audience")
    r = client.get("/api/me", headers={"cf-ray": "x", "cf-access-jwt-assertion": "eyJhbGciOiJSUzI1NiJ9.e30.c2ln"})
    assert r.status_code == 401


def test_actions_need_the_csrf_header(client):
    r = client.post("/api/tasks", json={"workspace": "ws_city", "persona": "p_city_bronx", "prompt": "test"})
    assert r.status_code == 403


def test_cross_site_origin_is_refused(client):
    r = client.post("/api/tasks", headers={**H, "origin": "https://evil.example"},
                    json={"workspace": "ws_city", "persona": "p_city_bronx", "prompt": "test"})
    assert r.status_code == 403


def test_invited_user_cannot_see_owner_tasks(client):
    owner_task = tally.rows("SELECT id::text FROM tally.tasks WHERE created_by = 'owner@local' LIMIT 1")[0]["id"]
    as_user("guest@example.com", "invited")
    assert client.get(f"/api/tasks/{owner_task}").status_code == 404           # indistinguishable from missing
    assert client.get(f"/api/tasks/{owner_task}/events").status_code == 404
    assert all(t["id"] != owner_task for t in client.get("/api/tasks").json())
    assert client.post(f"/api/tasks/{owner_task}/stop", headers=H).status_code == 404


def test_invited_budget_is_capped(client):
    as_user("guest@example.com", "invited")
    r = client.post("/api/tasks", headers=H, json={"workspace": "ws_city", "persona": "p_city_bronx", "prompt": "test", "budget_usd": 1.5})
    assert r.status_code == 400 and "at most" in r.json()["detail"]


def test_file_paths_cannot_escape(client):
    t = tally.rows("SELECT id::text FROM tally.tasks WHERE status='succeeded' LIMIT 1")[0]["id"]
    for path in ("../task/prompt.txt", "..%2F..%2F.env", "%2Fetc%2Fpasswd"):
        assert client.get(f"/api/tasks/{t}/files/{path}").status_code == 404
