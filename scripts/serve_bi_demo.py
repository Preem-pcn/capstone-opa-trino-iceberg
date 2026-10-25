"""Loopback-only QAR demo server: OIDC sign-in, one dashboard per role, flight API.

Sign-in is the OIDC authorization code flow with PKCE. Keycloak serves it locally;
another provider (for example Entra ID) only needs OIDC_ISSUER and .secrets/oidc-client.json.
The "roles" claim picks the Metabase dashboard and the Trino user for the flight API,
so OPA filters every query by the signed-in role. Sessions live in memory: restarting
the server signs everyone out. No Metabase admin credentials, embedding secret,
Trino password or arbitrary file access is exposed. Keep it bound to loopback.
"""

import argparse
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from datetime import date, datetime
from decimal import Decimal
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import jwt

from bi_demo_settings import OIDC_ISSUER, ROLES, ROOT, WEB_URL, b64url, embed_url, read_secret
from flight_api import FlightAPIError, flight_detail, list_flights

PAGE = ROOT / "bi/web/qar-flight-analytics-capstone-metabase.html"
DISCOVERY_URL = os.environ.get("OIDC_DISCOVERY_URL", OIDC_ISSUER + "/.well-known/openid-configuration")
SESSION_SECONDS = 8 * 3600
LOGIN_SECONDS = 600
NO_ROLE = "Your account has no dashboard role. Ask an administrator to assign safety, operations or engineering."

SESSIONS = {}  # session cookie -> signed-in user
LOGINS = {}  # OIDC state -> PKCE verifier and nonce of a sign-in in progress
LOCK = threading.Lock()
PROVIDER = {}


class LoginError(Exception):
    pass


def json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError("Unsupported JSON value")


def provider():
    """OIDC discovery document and the provider's signing keys, fetched once per server start."""
    if not PROVIDER:
        with urlopen(DISCOVERY_URL, timeout=10) as response:
            config = json.load(response)
        PROVIDER.update(config=config, keys=jwt.PyJWKClient(config["jwks_uri"]))
    return PROVIDER["config"], PROVIDER["keys"]


def begin_login():
    config, _ = provider()
    client = read_secret("oidc-client.json")
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    now = time.time()
    with LOCK:
        for table in (LOGINS, SESSIONS):
            for key in [key for key, value in table.items() if value["expires"] < now]:
                del table[key]
        LOGINS[state] = {"nonce": nonce, "verifier": verifier, "expires": now + LOGIN_SECONDS}
    query = urlencode({"response_type": "code", "client_id": client["client_id"],
                       "redirect_uri": WEB_URL + "/callback", "scope": "openid profile email",
                       "state": state, "nonce": nonce, "code_challenge_method": "S256",
                       "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest())})
    return config["authorization_endpoint"] + "?" + query, state


def finish_login(params, browser_state):
    """Exchange the code for an ID token, verify it, and return a new session cookie value."""
    state = params.get("state", [""])[0]
    with LOCK:
        pending = LOGINS.pop(state, None)
    if "error" in params:
        raise LoginError(params.get("error_description", params["error"])[0])
    # The state cookie ties the callback to the browser that started the sign-in.
    if not pending or pending["expires"] < time.time() or not hmac.compare_digest(state, browser_state or ""):
        raise LoginError("This sign-in link expired or was opened in a different browser. Sign in again.")
    config, keys = provider()
    client = read_secret("oidc-client.json")
    body = urlencode({"grant_type": "authorization_code", "code": params.get("code", [""])[0],
                      "redirect_uri": WEB_URL + "/callback", "client_id": client["client_id"],
                      "client_secret": client["client_secret"], "code_verifier": pending["verifier"]}).encode()
    request = Request(config["token_endpoint"], data=body,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urlopen(request, timeout=10) as response:
            id_token = json.load(response)["id_token"]
        claims = jwt.decode(id_token, keys.get_signing_key_from_jwt(id_token).key, algorithms=["RS256"],
                            audience=client["client_id"], issuer=OIDC_ISSUER, leeway=30,
                            options={"require": ["exp", "iat", "sub", "nonce"]})
    except (HTTPError, KeyError, jwt.PyJWTError):
        raise LoginError("The identity provider did not confirm this sign-in. Sign in again.") from None
    if not hmac.compare_digest(claims["nonce"], pending["nonce"]):
        raise LoginError("The sign-in response did not match this request. Sign in again.")
    roles = [role for role in claims.get("roles", []) if role in ROLES]
    session_id = secrets.token_urlsafe(32)
    with LOCK:
        SESSIONS[session_id] = {
            "user": claims.get("preferred_username") or claims["sub"], "name": claims.get("name", ""),
            # Exactly one known role selects a dashboard; none or several grants no data.
            "role": roles[0] if len(roles) == 1 else None,
            "id_token": id_token, "expires": time.time() + SESSION_SECONDS}
    return session_id


def cookie(name, value, path="/", max_age=SESSION_SECONDS):
    # ponytail: no Secure flag because the demo serves plain HTTP on localhost; add it behind HTTPS.
    return ("Set-Cookie", f"{name}={value}; HttpOnly; SameSite=Lax; Path={path}; Max-Age={max_age}")


def error_page(message):
    return (f'<!doctype html><meta charset="utf-8"><title>Sign-in problem</title>'
            f'<p>{html.escape(message)}</p><p><a href="/login">Sign in again</a></p>').encode()


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json; charset=utf-8", headers=()):
        if isinstance(data, dict):
            data = json.dumps(data, ensure_ascii=False, default=json_value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, *headers):
        self.reply(302, b"", "text/plain", [("Location", location), *headers])

    def cookies(self):
        return {name: morsel.value for name, morsel in SimpleCookie(self.headers.get("Cookie", "")).items()}

    def session(self):
        session_id = self.cookies().get("qar_session", "")
        with LOCK:
            current = SESSIONS.get(session_id)
            if current and current["expires"] < time.time():
                del SESSIONS[session_id]
                current = None
        return session_id, current

    def do_GET(self):
        url = urlsplit(self.path)
        path = url.path
        if self.headers.get("Host") not in {f"localhost:{self.server.server_port}", f"127.0.0.1:{self.server.server_port}"}:
            self.reply(403, {"error": "Use the loopback demo URL."})
            return
        try:
            if path == "/api/bi/health":
                self.reply(200, {"service": "qar-capstone-metabase-demo", "page_ready": PAGE.is_file(),
                                 "configured": (ROOT / ".secrets/metabase-embed.json").is_file()})
                return
            if path == "/login":
                location, state = begin_login()
                self.redirect(location, cookie("qar_login", state, "/callback", LOGIN_SECONDS))
                return
            if path == "/callback":
                session_id = finish_login(parse_qs(url.query), self.cookies().get("qar_login"))
                self.redirect("/", cookie("qar_session", session_id), cookie("qar_login", "", "/callback", 0))
                return
            session_id, user = self.session()
            if path == "/logout":
                with LOCK:
                    SESSIONS.pop(session_id, None)
                # Also end the identity provider's session, or the next sign-in would skip the password.
                location = "/" if not user else provider()[0]["end_session_endpoint"] + "?" + urlencode({
                    "id_token_hint": user["id_token"], "post_logout_redirect_uri": WEB_URL + "/",
                    "client_id": read_secret("oidc-client.json")["client_id"]})
                self.redirect(location, cookie("qar_session", "", max_age=0))
                return
            if not user:
                if path.startswith("/api/"):
                    self.reply(401, {"error": "Sign in again."})
                else:
                    self.redirect("/login")
                return
            role = ROLES.get(user["role"])
            if path == "/api/me":
                self.reply(200, {"user": user["user"], "name": user["name"], "role": user["role"],
                                 "role_label": role and role["label"], "scope": role and role["scope"],
                                 "trino_user": role and role["trino_user"]})
            elif path in {"/", "/" + PAGE.name}:
                self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self.reply(204, b"", "image/x-icon")
            elif path not in {"/api/bi/embed", "/metabase", "/api/flights", "/api/flights/detail"}:
                self.reply(404, {"error": "Not found"})
            elif not role:
                self.reply(403, {"error": NO_ROLE})
            elif path == "/api/flights":
                self.reply(200, list_flights(role["trino_user"]))
            elif path == "/api/flights/detail":
                self.reply(200, flight_detail(parse_qs(url.query).get("id", [""])[0], role["trino_user"]))
            else:
                dashboard_id = int(read_secret("metabase-embed.json")["dashboards"][user["role"]])
                if path == "/metabase":
                    self.redirect(embed_url(dashboard_id))
                else:
                    self.reply(200, {"embed_url": embed_url(dashboard_id), "refresh_after_seconds": 480,
                                     "dashboard_id": dashboard_id, "role": user["role"],
                                     "role_label": role["label"], "query_identity": role["trino_user"]})
        except LoginError as error:
            self.reply(400, error_page(str(error)), "text/html; charset=utf-8")
        except FlightAPIError as error:
            self.reply(error.status, {"error": str(error)})
        except (FileNotFoundError, KeyError, ValueError):
            self.reply(503, {"error": "Run setup_bi_demo.py to configure the local embedded dashboards."})
        except OSError:  # includes URLError: the identity provider is not reachable
            self.reply(503, error_page("The sign-in service is not reachable. Start Keycloak and try again."),
                       "text/html; charset=utf-8")

    def log_message(self, fmt, *args):
        # Do not log URLs containing tokens, codes or arbitrary client-supplied strings.
        print(f"{self.command} {urlsplit(self.path).path.split('?')[0]}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    server = ThreadingHTTPServer((os.environ.get("BI_WEB_BIND", "127.0.0.1"), args.port), Handler)
    print(f"QAR Gold Reports: {WEB_URL}/#gold", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
