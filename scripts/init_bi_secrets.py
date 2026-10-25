"""Create the SSO BI demo's local secrets. Reruns keep existing values.

Writes only under .secrets/ (git-ignored); standard library only:
- trino-users.json + trino/password.db  Trino login per user (PBKDF2 file authenticator)
- trino.env / keycloak.env              values docker compose passes to Trino and Keycloak
- oidc-client.json                      the web backend's Keycloak client
- demo-logins.json + keycloak/qar-realm.json  demo users, roles and the realm Keycloak imports
"""
import hashlib
import json
import secrets

from bi_demo_settings import DEMO_USERS, ROLES, SECRETS, TRINO_USERS, WEB_URL, write_json

PBKDF2_ITERATIONS = 100_000


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


def realm(client, logins):
    return {
        "realm": "qar", "enabled": True, "sslRequired": "external",
        "roles": {"realm": [{"name": role, "description": info["scope"]} for role, info in ROLES.items()]},
        "clients": [{
            "clientId": client["client_id"], "secret": client["client_secret"], "enabled": True,
            "protocol": "openid-connect", "publicClient": False, "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False, "implicitFlowEnabled": False,
            "redirectUris": [WEB_URL + "/callback"], "webOrigins": [],
            "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": WEB_URL + "/"},
            # Same claim name Entra ID uses for app roles, so the backend reads both the same way.
            "protocolMappers": [{
                "name": "realm roles", "protocol": "openid-connect",
                "protocolMapper": "oidc-usermodel-realm-role-mapper",
                "config": {"claim.name": "roles", "multivalued": "true", "jsonType.label": "String",
                           "id.token.claim": "true", "access.token.claim": "true", "userinfo.token.claim": "true"}}],
        }],
        "users": [{
            "username": username, "enabled": True, "emailVerified": True, "email": f"{username}@qar.local",
            "firstName": username.split(".")[0].title(), "lastName": "Demo",
            "credentials": [{"type": "password", "value": login["password"], "temporary": False}],
            "realmRoles": [login["role"]] if login["role"] else [],
        } for username, login in logins.items()],
    }


def main():
    trino_users = kept("trino-users.json", lambda: {user: token() for user in TRINO_USERS})
    write_text(SECRETS / "trino/password.db",
               "\n".join(pbkdf2_line(user, trino_users[user]) for user in TRINO_USERS) + "\n")
    service = kept("service-secrets.json", lambda: {
        "TRINO_SHARED_SECRET": secrets.token_hex(32), "TRINO_KEYSTORE_PASSWORD": token(),
        "KC_BOOTSTRAP_ADMIN_PASSWORD": token()})
    write_text(SECRETS / "trino.env", f"TRINO_SHARED_SECRET={service['TRINO_SHARED_SECRET']}\n"
                                      f"TRINO_KEYSTORE_PASSWORD={service['TRINO_KEYSTORE_PASSWORD']}\n")
    write_text(SECRETS / "keycloak.env", "KC_BOOTSTRAP_ADMIN_USERNAME=admin\n"
                                         f"KC_BOOTSTRAP_ADMIN_PASSWORD={service['KC_BOOTSTRAP_ADMIN_PASSWORD']}\n")
    client = kept("oidc-client.json", lambda: {"client_id": "qar-web", "client_secret": secrets.token_hex(32)})
    logins = kept("demo-logins.json", lambda: {name: {"password": token(), "role": role}
                                               for name, role in DEMO_USERS.items()})
    write_json(SECRETS / "keycloak/qar-realm.json", realm(client, logins))
    (SECRETS / "trino-public").mkdir(exist_ok=True)
    print("Secrets ready in .secrets/ (demo logins: .secrets/demo-logins.json)")


if __name__ == "__main__":
    main()
