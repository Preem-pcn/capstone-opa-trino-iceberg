"""OpenID Connect sign-in (authorization code + PKCE) and server-side sessions.

Any provider that publishes OIDC discovery works. Google is the default: it proves who the
person is (a verified email) but sends no role, so the role comes from role-assignments.json.
With ROLES_FROM=claim the role comes from the ID token instead (Entra ID, Keycloak).

Sessions live in this process's memory: run a single worker, and a restart signs everyone out.
The browser only ever holds a random session id; ID tokens stay here.
"""
import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt

from . import settings

GOOGLE = "https://accounts.google.com"
REDIRECT_URI = settings.PUBLIC_URL + "/callback"


class LoginError(Exception):
    """A sign-in that has to start again; the message is shown to the person."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Provider:
    def __init__(self, issuer: str, client_id: str, client_secret: str):
        self.issuer, self.client_id, self.client_secret = issuer, client_id, client_secret
        self._metadata: dict | None = None
        self._jwks: jwt.PyJWKClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def metadata(self) -> dict:
        """The provider's discovery document, fetched once per process."""
        if self._metadata is None:
            response = httpx.get(self.issuer + "/.well-known/openid-configuration", timeout=10)
            response.raise_for_status()
            self._metadata = response.json()
            self._jwks = jwt.PyJWKClient(self._metadata["jwks_uri"])
        return self._metadata

    def signing_key(self, id_token: str):
        self.metadata()
        return self._jwks.get_signing_key_from_jwt(id_token).key

    def authorization_url(self, state: str, nonce: str, verifier: str) -> str:
        query = {"response_type": "code", "client_id": self.client_id, "redirect_uri": REDIRECT_URI,
                 "scope": "openid email profile", "state": state, "nonce": nonce,
                 "code_challenge_method": "S256", "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
                 # Ask which account to use rather than silently reusing the browser's Google session.
                 "prompt": "select_account"}
        return self.metadata()["authorization_endpoint"] + "?" + urlencode(query)

    def exchange(self, code: str, verifier: str) -> str:
        """Swap the one-time code for an ID token, server to server."""
        response = httpx.post(self.metadata()["token_endpoint"], timeout=10, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
            "client_id": self.client_id, "client_secret": self.client_secret, "code_verifier": verifier})
        if response.status_code != 200 or "id_token" not in response.json():
            raise LoginError("The identity provider did not confirm this sign-in. Sign in again.")
        return response.json()["id_token"]

    def verify(self, id_token: str, nonce: str) -> dict:
        # Google ID tokens carry either issuer form.
        issuers = [self.issuer, "accounts.google.com"] if self.issuer == GOOGLE else [self.issuer]
        try:
            claims = jwt.decode(id_token, self.signing_key(id_token), algorithms=["RS256"], audience=self.client_id,
                                issuer=issuers, leeway=30, options={"require": ["exp", "iat", "sub", "nonce"]})
        except jwt.PyJWTError:
            raise LoginError("The identity provider did not confirm this sign-in. Sign in again.") from None
        if not hmac.compare_digest(str(claims["nonce"]), nonce):
            raise LoginError("The sign-in response did not match this request. Sign in again.")
        return claims

    def logout_url(self, id_token: str) -> str | None:
        """The provider's own sign-out, where it offers one. Google does not."""
        endpoint = self.metadata().get("end_session_endpoint")
        if not endpoint:
            return None
        return endpoint + "?" + urlencode({"id_token_hint": id_token, "client_id": self.client_id,
                                           "post_logout_redirect_uri": settings.PUBLIC_URL + "/"})


PROVIDER = Provider(settings.OIDC_ISSUER, settings.OIDC_CLIENT_ID, settings.OIDC_CLIENT_SECRET)


@dataclass
class Session:
    user: str
    name: str
    role: str | None   # exactly one known role, or None (no data)
    id_token: str
    expires: float


class Store:
    """Signed-in sessions and sign-ins in progress, in this process's memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        # state -> (nonce, PKCE verifier, page to return to, expires)
        self._logins: dict[str, tuple[str, str, str, float]] = {}

    def _prune(self, now: float):
        for sid in [k for k, s in self._sessions.items() if s.expires < now]:
            del self._sessions[sid]
        for state in [k for k, pending in self._logins.items() if pending[3] < now]:
            del self._logins[state]

    def begin(self, state: str, nonce: str, verifier: str, next_url: str):
        with self._lock:
            self._prune(time.time())
            self._logins[state] = (nonce, verifier, next_url, time.time() + settings.LOGIN_SECONDS)

    def take(self, state: str, browser_state: str | None) -> tuple[str, str, str]:
        """The nonce, verifier and return page of a sign-in this browser started, usable once."""
        with self._lock:
            pending = self._logins.pop(state, None)
        # The state cookie ties the callback to the browser that started the sign-in.
        if not pending or pending[3] < time.time() or not hmac.compare_digest(state, browser_state or ""):
            raise LoginError("This sign-in link expired or was opened in a different browser. Sign in again.")
        return pending[0], pending[1], pending[2]

    def create(self, session: Session) -> str:
        sid = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[sid] = session
        return sid

    def get(self, sid: str) -> Session | None:
        with self._lock:
            session = self._sessions.get(sid)
            if session and session.expires < time.time():
                del self._sessions[sid]
                return None
            return session

    def drop(self, sid: str) -> Session | None:
        with self._lock:
            return self._sessions.pop(sid, None)


STORE = Store()


def begin_login(next_url: str) -> tuple[str, str]:
    """A new sign-in: returns its state (for the browser cookie) and the provider URL to send it to.

    next_url must already be checked (main.safe_next); it stays here, not in the browser.
    """
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    url = PROVIDER.authorization_url(state, nonce, verifier)
    STORE.begin(state, nonce, verifier, next_url)
    return state, url


def roles_for(claims: dict) -> list[str]:
    if settings.ROLES_FROM == "claim":
        roles = claims.get("roles", [])
        return [roles] if isinstance(roles, str) else list(roles)
    # Read on every sign-in, so edits apply at the person's next sign-in without a restart.
    path = settings.SECRETS_DIR / "role-assignments.json"
    table = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    value = {email.strip().lower(): role for email, role in table.items()}.get(claims["email"].strip().lower())
    return [value] if isinstance(value, str) else list(value or [])


def sign_in(code: str, state: str, browser_state: str | None) -> tuple[Session, str]:
    """Finish a sign-in: the new session and the page to return to."""
    nonce, verifier, next_url = STORE.take(state, browser_state)
    id_token = PROVIDER.exchange(code, verifier)
    claims = PROVIDER.verify(id_token, nonce)
    if settings.ROLES_FROM == "assignments" and not (claims.get("email") and claims.get("email_verified") in (True, "true")):
        raise LoginError("This account has no verified email address, so no role can be matched to it.")
    if settings.ALLOWED_DOMAIN and str(claims.get("hd", "")).lower() != settings.ALLOWED_DOMAIN:
        raise LoginError(f"Sign in with your {settings.ALLOWED_DOMAIN} account.")
    known = [role for role in roles_for(claims) if role in settings.ROLES]
    session = Session(
        user=claims.get("email") or claims.get("preferred_username") or claims["sub"],
        name=claims.get("name", ""),
        # Exactly one known role selects a dashboard; none or several grants no data.
        role=known[0] if len(known) == 1 else None,
        id_token=id_token, expires=time.time() + settings.SESSION_SECONDS)
    return session, next_url
