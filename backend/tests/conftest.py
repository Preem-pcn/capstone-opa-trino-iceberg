"""Test configuration: settings are read at import, so set the environment before app imports."""
import json
import os
import tempfile
from pathlib import Path

_root = Path(tempfile.mkdtemp(prefix="qar-backend-test-"))
SECRETS = _root / "secrets"
STATIC = _root / "static"
(SECRETS / "trino-public").mkdir(parents=True)
(STATIC / "assets").mkdir(parents=True)
(STATIC / "index.html").write_text("<!doctype html><title>QAR</title>", encoding="utf-8")
(STATIC / "assets" / "app.js").write_text("console.log('qar')", encoding="utf-8")
(_root / "outside.txt").write_text("not part of the client", encoding="utf-8")
(SECRETS / "role-assignments.json").write_text(json.dumps({
    "Ops@Example.com": "operations", "safety@example.com": "safety",
    "two@example.com": ["safety", "operations"]}), encoding="utf-8")
(SECRETS / "metabase-embed.json").write_text(json.dumps({
    "metabase_url": "http://localhost:3002", "secret": "a" * 64,
    "dashboards": {"safety": 1, "operations": 2, "engineering": 3}}), encoding="utf-8")

os.environ.update({"SECRETS_DIR": str(SECRETS), "CLIENT_DIST": str(STATIC), "PUBLIC_URL": "http://localhost:8766",
                   "DEV_ORIGINS": "http://localhost:5173",
                   "OIDC_CLIENT_ID": "test-client", "OIDC_CLIENT_SECRET": "test-secret"})
# Inside the image roles.json sits next to the app; from a checkout use the repo's copy.
os.environ.setdefault("ROLES_FILE", str(next(p for p in [Path("/app/roles.json"),
                                                         Path(__file__).resolve().parents[2] / "bi/roles.json"] if p.exists())))
