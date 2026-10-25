"""Configuration from the environment, read once at start.

Secrets are files in SECRETS_DIR, the repo's .secrets/ mounted read-only (see docker-compose.app.yaml):
trino-users.json and trino-public/trino.crt from init_bi_secrets.py, metabase-embed.json from
setup_bi_demo.py, and role-assignments.json that you edit. Nothing secret is built into the image.
"""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:8766").rstrip("/")
PUBLIC_HOST = urlsplit(PUBLIC_URL).hostname or "localhost"
# Origins a finished sign-in may return to: this site, plus DEV_ORIGINS (comma-separated, e.g. the
# Vite dev server at http://localhost:5173, which proxies to this backend).
ALLOWED_ORIGINS = {"{0.scheme}://{0.netloc}".format(urlsplit(PUBLIC_URL))} | {
    origin.strip().rstrip("/") for origin in os.environ.get("DEV_ORIGINS", "").split(",") if origin.strip()}

OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "https://accounts.google.com").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
# "assignments": the role comes from role-assignments.json by verified email. Use it for providers
#   that send no role, such as Google.
# "claim": the role comes from the ID token's "roles" claim (Entra ID app roles, Keycloak realm roles).
ROLES_FROM = os.environ.get("ROLES_FROM", "assignments")
# Optional Google Workspace domain (the "hd" claim); empty accepts any verified account.
ALLOWED_DOMAIN = os.environ.get("ALLOWED_DOMAIN", "").strip().lower()

SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", "/run/qar-secrets"))
CLIENT_DIST = Path(os.environ.get("CLIENT_DIST", "/app/static"))
TRINO_HOST = os.environ.get("TRINO_HOST", "trino")
TRINO_PORT = int(os.environ.get("TRINO_PORT", "8443"))

SESSION_SECONDS = int(os.environ.get("SESSION_SECONDS", str(8 * 3600)))
LOGIN_SECONDS = 600
EMBED_SECONDS = 600
# Browsers only send Secure cookies over HTTPS, so the flag follows the public URL.
COOKIE_SECURE = PUBLIC_URL.startswith("https://")

# Role -> Trino user evaluated by opa/trino.rego. Same file the stack scripts read (bi/roles.json).
ROLES = json.loads(Path(os.environ.get("ROLES_FILE", "/app/roles.json")).read_text(encoding="utf-8"))

if ROLES_FROM not in {"assignments", "claim"}:
    raise RuntimeError("ROLES_FROM must be 'assignments' or 'claim'.")
