"""HTTP routes: sign-in, the role-scoped data API (flights, sensors, catalog, SQL), signed
dashboards and the React client.

The routes and JSON match what the client expects (client/src/api.ts). Audit events are
JSON lines on stdout (docker compose logs backend): who signed in, with which role, and
which data or dashboard they opened. Tokens and codes are never logged.
"""
import html
import json
import time
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth, data, settings

NO_ROLE = "Your account has no dashboard role. Ask an administrator to assign safety, operations or engineering."
UNREACHABLE = "The sign-in service is not reachable. Try again in a moment."
SESSION_COOKIE, LOGIN_COOKIE = "qar_session", "qar_login"

app = FastAPI(title="QAR backend", docs_url=None, redoc_url=None, openapi_url=None)
# Requests must be addressed to this site, not to whatever name reaches the port.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[settings.PUBLIC_HOST, "localhost", "127.0.0.1"])
app.add_middleware(GZipMiddleware, minimum_size=2048)   # sensor series for a long flight are a few MB of JSON


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if not request.url.path.startswith("/assets/"):   # hashed build files may be cached
        response.headers["Cache-Control"] = "no-store"
    return response


def audit(event: str, **fields):
    print(json.dumps({"ts": round(time.time(), 3), "event": event, **fields}), flush=True)


def safe_next(value: str) -> str:
    """Where a finished sign-in may land: a path on this site, or a page on an allowed origin
    (the dev server). Anything else returns to "/", so /login cannot redirect people off-site."""
    if any(c in value for c in "\t\r\n\\"):   # browsers strip or rewrite these, e.g. "/\t/evil" -> "//evil"
        return "/"
    if value.startswith("/") and not value.startswith("//"):
        return value
    parts = urlsplit(value)
    return value if f"{parts.scheme}://{parts.netloc}" in settings.ALLOWED_ORIGINS else "/"


def error_page(message: str, status: int) -> HTMLResponse:
    return HTMLResponse(f'<!doctype html><meta charset="utf-8"><title>Sign-in problem</title>'
                        f'<p>{html.escape(message)}</p><p><a href="/login">Sign in again</a></p>', status)


@app.exception_handler(HTTPException)
async def api_error(_: Request, error: HTTPException):
    return JSONResponse({"error": error.detail}, error.status_code)


@app.exception_handler(data.DataError)
async def data_error(_: Request, error: data.DataError):
    return JSONResponse({"error": str(error)}, error.status)


def session_of(request: Request) -> auth.Session | None:
    return auth.STORE.get(request.cookies.get(SESSION_COOKIE, ""))


def signed_in(request: Request) -> auth.Session:
    session = session_of(request)
    if not session:
        raise HTTPException(401, "Sign in again.")
    return session


def with_role(session: auth.Session = Depends(signed_in)) -> tuple[auth.Session, dict]:
    if not session.role:
        raise HTTPException(403, NO_ROLE)
    return session, settings.ROLES[session.role]


@app.get("/api/bi/health")
def health():
    return {"service": "qar-backend", "client_ready": (settings.CLIENT_DIST / "index.html").is_file(),
            "sign_in_configured": auth.PROVIDER.configured,
            "dashboards_configured": (settings.SECRETS_DIR / "metabase-embed.json").is_file()}


@app.get("/login")
def login(next: str = "/"):
    if not auth.PROVIDER.configured:
        return error_page("Sign-in is not configured. Put the OAuth client ID and secret in .secrets/oidc.env, "
                          "then restart the backend.", 503)
    try:
        state, url = auth.begin_login(safe_next(next))
    except (httpx.HTTPError, OSError):
        return error_page(UNREACHABLE, 503)
    response = RedirectResponse(url, 302)
    response.set_cookie(LOGIN_COOKIE, state, max_age=settings.LOGIN_SECONDS, path="/callback",
                        httponly=True, samesite="lax", secure=settings.COOKIE_SECURE)
    return response


@app.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    if error:
        return error_page(error_description or error, 400)
    try:
        session, next_url = auth.sign_in(code, state, request.cookies.get(LOGIN_COOKIE))
    except auth.LoginError as failure:
        audit("sign_in_refused", reason=str(failure))
        return error_page(str(failure), 400)
    except (httpx.HTTPError, OSError):
        return error_page(UNREACHABLE, 503)
    audit("sign_in", user=session.user, role=session.role)
    response = RedirectResponse(next_url, 302)
    response.set_cookie(SESSION_COOKIE, auth.STORE.create(session), max_age=settings.SESSION_SECONDS, path="/",
                        httponly=True, samesite="lax", secure=settings.COOKIE_SECURE)
    response.delete_cookie(LOGIN_COOKIE, path="/callback")
    return response


@app.get("/logout")
def logout(request: Request):
    session = auth.STORE.drop(request.cookies.get(SESSION_COOKIE, ""))
    location = "/"
    if session:
        audit("sign_out", user=session.user)
        try:
            location = auth.PROVIDER.logout_url(session.id_token) or "/"
        except (httpx.HTTPError, OSError):
            pass
    response = RedirectResponse(location, 302)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/me")
def me(session: auth.Session = Depends(signed_in)):
    role = settings.ROLES.get(session.role) if session.role else None
    return {"user": session.user, "name": session.name, "role": session.role,
            "role_label": role and role["label"], "scope": role and role["scope"], "trino_user": role and role["trino_user"]}


@app.get("/api/flights")
def flights(context=Depends(with_role)):
    session, role = context
    audit("flights", user=session.user, role=session.role)
    return data.list_flights(role["trino_user"], session.user)


@app.get("/api/flights/detail")
def flight_detail(id: str = "", context=Depends(with_role)):
    session, role = context
    audit("flight_detail", user=session.user, role=session.role)
    return data.flight_detail(id, role["trino_user"], session.user)


@app.get("/api/flights/sensors")
def flight_sensors(id: str = "", context=Depends(with_role)):
    session, role = context
    audit("flight_sensors", user=session.user, role=session.role)
    return data.flight_sensors(id, role["trino_user"], session.user)


@app.get("/api/catalog")
def catalog(context=Depends(with_role)):
    session, role = context
    return data.catalog(role["trino_user"], session.user)


class SqlRequest(BaseModel):
    sql: str


# A JSON body: a cross-site form cannot send it, and the session cookie is SameSite=Lax.
@app.post("/api/sql")
def sql(body: SqlRequest, context=Depends(with_role)):
    session, role = context
    audit("sql", user=session.user, role=session.role, sql=body.sql[:2000])
    return data.run_sql(body.sql, role["trino_user"], session.user)


@app.get("/api/bi/embed")
def embed(context=Depends(with_role)):
    session, role = context
    dashboard_id, url = data.dashboard_link(session.role)
    audit("dashboard", user=session.user, role=session.role, dashboard=dashboard_id)
    return {"embed_url": url, "refresh_after_seconds": settings.EMBED_SECONDS - 120, "dashboard_id": dashboard_id,
            "role": session.role, "role_label": role["label"], "query_identity": role["trino_user"]}


@app.get("/metabase")
def metabase(context=Depends(with_role)):
    session, _ = context
    dashboard_id, url = data.dashboard_link(session.role)
    audit("dashboard", user=session.user, role=session.role, dashboard=dashboard_id)
    return RedirectResponse(url, 302)


# Last: everything else is the React client. Its files are served only to signed-in browsers,
# and only from the build folder; unknown paths get index.html so client-side routes work.
@app.get("/{path:path}")
def client(path: str, request: Request):
    if path.startswith("api/"):
        return JSONResponse({"error": "Not found"}, 404)
    if not session_of(request):
        here = "/" + path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse("/login?" + urlencode({"next": here}), 302)
    root = settings.CLIENT_DIST.resolve()
    if not (root / "index.html").is_file():
        return PlainTextResponse("The web client is not built into this image.", 503)
    target = (root / path).resolve()
    if path and target.is_file() and target.is_relative_to(root):
        return FileResponse(target)
    return FileResponse(root / "index.html")
