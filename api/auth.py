"""Who is calling, and what they may do.

Tally sits behind a Cloudflare Tunnel, and cloudflared connects from this machine, so every internet request also
arrives from 127.0.0.1. Source address therefore proves nothing. The rule instead:

  * A request that came through Cloudflare (Cloudflare always adds CF-Ray / CF-Connecting-IP, and the edge sets them,
    so a visitor cannot strip them) MUST carry a valid Cloudflare Access JWT for Tally's Access application.
    If Access is not configured (no audience tag), such requests are refused: fail closed.
  * A request with no Cloudflare headers can only come from this machine (the API binds to 127.0.0.1), for example
    the owner over an SSH tunnel. It is treated as the owner.

Owners see every task. Invited users see only their own tasks and get tighter limits.
"""
import os
from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

CF_TEAM = os.environ.get("TALLY_CF_TEAM", "tight-smoke-1308")
CF_AUD = os.environ.get("TALLY_CF_AUD", "")                   # Access application audience tag
OWNERS = {e.strip().lower() for e in os.environ.get("TALLY_OWNERS", "karthickmit25@gmail.com").split(",") if e.strip()}

LIMITS = {   # per person
    "owner": {"concurrent": 2, "tasks_per_day": 200, "usd_per_day": 3.00, "max_budget": 2.00},
    "invited": {"concurrent": 1, "tasks_per_day": 10, "usd_per_day": 1.00, "max_budget": 0.50},
}

_jwks: PyJWKClient | None = None


@dataclass(frozen=True)
class User:
    email: str
    role: str                      # owner | invited

    @property
    def limits(self):
        return LIMITS[self.role]

    def can_see(self, created_by: str) -> bool:
        return self.role == "owner" or created_by == self.email


def _verify(token: str) -> str:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(f"https://{CF_TEAM}.cloudflareaccess.com/cdn-cgi/access/certs", cache_keys=True)
    key = _jwks.get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=CF_AUD, issuer=f"https://{CF_TEAM}.cloudflareaccess.com")
    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(403, "Access token has no email")
    return email


def current_user(request: Request) -> User:
    via_cloudflare = any(h in request.headers for h in ("cf-ray", "cf-connecting-ip", "cf-access-jwt-assertion"))
    if not via_cloudflare:
        return User("owner@local", "owner")
    if not CF_AUD:
        raise HTTPException(503, "Remote access is not configured")
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    if not token:
        raise HTTPException(401, "Sign in through Cloudflare Access")
    try:
        email = _verify(token)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(401, "Invalid or expired sign-in")
    return User(email, "owner" if email in OWNERS else "invited")


def check_csrf(request: Request):
    """State-changing requests must carry a custom header (a cross-site form or image cannot add one)
    and, if the browser sends an Origin, it must be this site."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.headers.get("x-tally-request") != "1":
            raise HTTPException(403, "Missing request header")
        origin = request.headers.get("origin")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if origin and host and origin.split("://", 1)[-1] != host:
            raise HTTPException(403, "Cross-site request refused")
