"""Local, fixed Trino identity for this demo; not viewer authentication."""
import json
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / ".secrets/bi-demo-settings.json"
IDENTITIES = ("safety_analyst", "admin")


def get_query_identity():
    identity = json.loads(SETTINGS.read_text(encoding="utf-8"))["query_identity"] if SETTINGS.exists() else "safety_analyst"
    if identity not in IDENTITIES:
        raise ValueError("Unsupported fixed BI demo identity")
    return identity


def set_query_identity(identity):
    if identity not in IDENTITIES:
        raise ValueError("Unsupported fixed BI demo identity")
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps({"query_identity": identity}) + "\n", encoding="utf-8")
    temporary.replace(SETTINGS)
