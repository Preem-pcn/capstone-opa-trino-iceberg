"""Create the BI stack's local secrets. Reruns keep existing values.

Writes only under .secrets/ (git-ignored); standard library only:
- trino-users.json + trino/password.db  Trino login per user (PBKDF2 file authenticator)
- trino.env                             values docker compose passes to Trino
- oidc.env                              the backend's OIDC client (Google); template only, you fill it in
- role-assignments.json                 signed-in email -> role; template only, you fill it in
"""
import hashlib
import json
import secrets

from bi_demo_settings import SECRETS, TRINO_USERS, write_json

PBKDF2_ITERATIONS = 100_000

OIDC_TEMPLATE = """\
# Google OAuth client for the backend (Google Cloud console > Google Auth Platform > Clients,
# type "Web application", authorized redirect URI http://localhost:8766/callback).
OIDC_CLIENT_ID=
OIDC_CLIENT_SECRET=
# Optional: only accept accounts from this Google Workspace domain (the hd claim).
ALLOWED_DOMAIN=
# Another OIDC provider: set its issuer. Entra ID and Keycloak send roles in the token, so use ROLES_FROM=claim.
# OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0
# ROLES_FROM=claim
"""


def kept(name, make):
    """Load .secrets/<name>, adding any keys from make() that are not stored yet."""
    path = SECRETS / name
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    merged = {**make(), **current}
    if merged != current:
        write_json(path, merged)
    return merged


def token():
    return secrets.token_urlsafe(24)


def write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def pbkdf2_line(user, password):
    # Trino file authenticator format: user:iterations:salt-hex:hash-hex. Trino 483 verifies
    # with PBKDF2WithHmacSHA1 (io.trino.plugin.password.file.EncryptionUtil).
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha1", password.encode(), salt, PBKDF2_ITERATIONS, 32)
    return f"{user}:{PBKDF2_ITERATIONS}:{salt.hex()}:{digest.hex()}"


def main():
    trino_users = kept("trino-users.json", lambda: {user: token() for user in TRINO_USERS})
    write_text(SECRETS / "trino/password.db",
               "\n".join(pbkdf2_line(user, trino_users[user]) for user in TRINO_USERS) + "\n")
    service = kept("service-secrets.json", lambda: {
        "TRINO_SHARED_SECRET": secrets.token_hex(32), "TRINO_KEYSTORE_PASSWORD": token()})
    write_text(SECRETS / "trino.env", f"TRINO_SHARED_SECRET={service['TRINO_SHARED_SECRET']}\n"
                                      f"TRINO_KEYSTORE_PASSWORD={service['TRINO_KEYSTORE_PASSWORD']}\n")
    # Templates the person running the stack completes; never overwritten once they exist.
    if not (SECRETS / "oidc.env").exists():
        write_text(SECRETS / "oidc.env", OIDC_TEMPLATE)
    if not (SECRETS / "role-assignments.json").exists():
        write_json(SECRETS / "role-assignments.json", {})
    (SECRETS / "trino-public").mkdir(exist_ok=True)
    configured = "OIDC_CLIENT_ID=\n" not in (SECRETS / "oidc.env").read_text(encoding="utf-8")
    print("Secrets ready in .secrets/" + ("" if configured else
          " · sign-in not configured yet: fill in .secrets/oidc.env and .secrets/role-assignments.json"))


if __name__ == "__main__":
    main()
