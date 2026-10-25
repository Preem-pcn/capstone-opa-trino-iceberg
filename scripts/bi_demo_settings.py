"""Roles, URLs and local secrets shared by the BI stack scripts.

Secrets live in git-ignored .secrets/ files created by init_bi_secrets.py.
Standard library only, so host scripts can import it without extra packages.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".secrets"
TRINO_CERT = SECRETS / "trino-public/trino.crt"

WEB_URL = os.environ.get("BI_PUBLIC_URL", "http://localhost:8766")

# Role -> Trino user evaluated by opa/trino.rego. One file, shared with the backend container.
ROLES = json.loads((ROOT / "bi/roles.json").read_text(encoding="utf-8"))
# Trino logins: the loader, one per role, and a user OPA always denies.
TRINO_USERS = ["dagster", "blocked_user", *(role["trino_user"] for role in ROLES.values())]


def read_secret(name):
    return json.loads((SECRETS / name).read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def trino_connection(user, **options):
    """HTTPS + password connection; the password file and certificate come from init_bi_secrets.py."""
    import trino
    return trino.dbapi.connect(host=os.environ.get("TRINO_HOST", "127.0.0.1"),
                               port=int(os.environ.get("TRINO_PORT", "8443")),
                               user=user, catalog="iceberg", http_scheme="https", verify=str(TRINO_CERT),
                               auth=trino.auth.BasicAuthentication(user, read_secret("trino-users.json")[user]),
                               **options)


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def embed_url(dashboard_id, seconds=600):
    """Metabase static-embed URL: an HS256 token naming one dashboard, signed with the shared secret."""
    config = read_secret("metabase-embed.json")
    now = int(time.time())
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = b64url(json.dumps({"resource": {"dashboard": int(dashboard_id)}, "params": {},
                                 "iat": now, "exp": now + seconds}, separators=(",", ":")).encode())
    unsigned = header + "." + payload
    signature = b64url(hmac.new(config["secret"].encode(), unsigned.encode(), hashlib.sha256).digest())
    return config["metabase_url"].rstrip("/") + "/embed/dashboard/" + unsigned + "." + signature + "#bordered=false&titled=false"
