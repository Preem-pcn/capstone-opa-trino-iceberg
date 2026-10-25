"""Sign-in, roles, data access and static files, against a fake OIDC provider.

The fake provider replaces only the network calls (discovery, code exchange, key download);
token verification, state/nonce checks and role lookup run as in production.
"""
import secrets
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
import pytest
import trino
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth, data, main, settings

ISSUER = "https://accounts.google.com"


@pytest.fixture
def idp(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issued: dict[str, str] = {}
    monkeypatch.setattr(auth.PROVIDER, "metadata", lambda: {
        "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_endpoint": "https://oauth2.googleapis.com/token",
        "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs"})
    monkeypatch.setattr(auth.PROVIDER, "signing_key", lambda token: key.public_key())
    monkeypatch.setattr(auth.PROVIDER, "exchange", lambda code, verifier: issued.pop(code))

    class FakeIdP:
        def token(self, nonce, signer=key, **claims):
            now = int(time.time())
            payload = {"iss": ISSUER, "aud": "test-client", "sub": "1234", "iat": now, "exp": now + 300,
                       "nonce": nonce, "email_verified": True, "name": "Test Person", **claims}
            return jwt.encode(payload, signer, algorithm="RS256")

        def sign_in(self, client, email="Ops@Example.com", nonce=None, next_url=None, **claims):
            start = client.get("/login" + (f"?{urlencode({'next': next_url})}" if next_url else ""), follow_redirects=False)
            query = parse_qs(urlsplit(start.headers["location"]).query)
            code = secrets.token_hex(8)
            issued[code] = self.token(nonce or query["nonce"][0], email=email, **claims)
            return client.get(f"/callback?code={code}&state={query['state'][0]}", follow_redirects=False)

    return FakeIdP()


@pytest.fixture
def client():
    return TestClient(main.app, base_url="http://localhost:8766")


def test_signed_out(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me").json() == {"error": "Sign in again."}
    assert client.get("/api/flights").status_code == 401
    page = client.get("/flights?tab=x", follow_redirects=False)
    assert page.status_code == 302 and page.headers["location"] == "/login?next=%2Fflights%3Ftab%3Dx"


def test_login_redirect(client, idp):
    response = client.get("/login", follow_redirects=False)
    target = urlsplit(response.headers["location"])
    query = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert query["client_id"] == ["test-client"]
    assert query["redirect_uri"] == ["http://localhost:8766/callback"]
    assert query["code_challenge_method"] == ["S256"] and query["prompt"] == ["select_account"]
    assert "email" in query["scope"][0].split()
    assert "Path=/callback" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]


def test_sign_in_assigns_role_by_email(client, idp):
    done = idp.sign_in(client, email="ops@example.com")   # assignment keys match case-insensitively
    assert done.status_code == 302 and done.headers["location"] == "/"
    me = client.get("/api/me").json()
    assert me["user"] == "ops@example.com" and me["role"] == "operations"
    assert me["trino_user"] == "operations_analyst" and me["role_label"] == "Operations"


@pytest.mark.parametrize("next_url", ["/reports?x=1", "http://localhost:5173/flights", "http://localhost:8766/sql"])
def test_returns_to_the_requested_page(client, idp, next_url):
    assert idp.sign_in(client, next_url=next_url).headers["location"] == next_url


@pytest.mark.parametrize("next_url", ["https://evil.example/", "//evil.example/x", "/\\evil.example",
                                      "/\t/evil.example", "http://localhost:9999/", "javascript:alert(1)"])
def test_return_page_off_site_falls_back_to_home(client, idp, next_url):
    assert idp.sign_in(client, next_url=next_url).headers["location"] == "/"


def test_unassigned_and_double_role_get_no_data(client, idp):
    for email in ["stranger@example.com", "two@example.com"]:
        idp.sign_in(client, email=email)
        assert client.get("/api/me").json()["role"] is None
        assert client.get("/api/flights").status_code == 403
        assert client.get("/api/bi/embed").json() == {"error": main.NO_ROLE}


@pytest.mark.parametrize("claims", [{"email_verified": False}, {"nonce": "not-the-one-we-sent"}])
def test_refused_sign_ins(client, idp, claims):
    assert idp.sign_in(client, **claims).status_code == 400
    assert client.get("/api/me").status_code == 401


def test_token_signed_by_another_key_is_refused(client, idp, monkeypatch):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    original = idp.token
    monkeypatch.setattr(idp, "token", lambda nonce, **claims: original(nonce, signer=other, **claims))
    assert idp.sign_in(client).status_code == 400


def test_callback_needs_the_browser_that_started(client, idp):
    start = client.get("/login", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    stranger = TestClient(main.app, base_url="http://localhost:8766")
    assert stranger.get(f"/callback?code=x&state={state}", follow_redirects=False).status_code == 400


def test_workspace_domain_restriction(client, idp, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_DOMAIN", "example.com")
    assert idp.sign_in(client, hd="elsewhere.org").status_code == 400
    assert idp.sign_in(client, hd="example.com").status_code == 302


def test_embed_link_names_only_the_role_dashboard(client, idp):
    idp.sign_in(client)
    info = client.get("/api/bi/embed").json()
    token = info["embed_url"].split("/embed/dashboard/")[1].split("#")[0]
    claims = jwt.decode(token, "a" * 64, algorithms=["HS256"])
    assert claims["resource"] == {"dashboard": 2} and claims["params"] == {}
    assert claims["exp"] - claims["iat"] == settings.EMBED_SECONDS
    assert info["query_identity"] == "operations_analyst"


def test_flights_query_as_role_user_tagged_with_person(client, idp, monkeypatch):
    calls = []
    monkeypatch.setattr(data, "query", lambda sql, user, person, parameters=None: calls.append((user, person)) or [])
    idp.sign_in(client)
    listing = client.get("/api/flights").json()
    assert listing["query_identity"] == "operations_analyst" and listing["flights"] == []
    assert calls == [("operations_analyst", "Ops@Example.com")]


def test_client_files_and_no_escape(client, idp):
    idp.sign_in(client)
    assert client.get("/assets/app.js").text == "console.log('qar')"
    assert "<title>QAR</title>" in client.get("/reports").text           # client route -> index.html
    assert "not part of the client" not in client.get("/..%2Foutside.txt").text
    assert client.get("/api/unknown").status_code == 404


def test_logout_ends_session(client, idp):
    idp.sign_in(client)
    assert client.get("/logout", follow_redirects=False).headers["location"] == "/"   # Google has no end-session endpoint
    assert client.get("/api/me").status_code == 401


def test_unknown_host_refused(client):
    assert TestClient(main.app, base_url="http://evil.example").get("/api/bi/health").status_code == 400


class FakeCursor:
    def __init__(self, rows=(), description=(("a", "integer"),), error=None, delay=0.0):
        self.rows, self.description, self.error, self.delay = list(rows), list(description), error, delay
        self.cancelled, self.sql = False, None

    def execute(self, sql, parameters=None):
        time.sleep(self.delay)
        if self.error:
            raise self.error
        self.sql = sql

    def fetchmany(self, size):
        return self.rows[:size]

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def trino_returns(monkeypatch):
    """Replace the Trino connection; returns the fake cursor and the (user, person) of each connect."""
    def use(**kwargs):
        cursor, calls = FakeCursor(**kwargs), []

        class Connection:
            def cursor(self):
                return cursor

            def close(self):
                pass

        monkeypatch.setattr(data, "connect", lambda user, person: calls.append((user, person)) or Connection())
        return cursor, calls
    return use


def trino_user_error(name, message):
    return trino.exceptions.TrinoUserError({"errorName": name, "errorType": "USER_ERROR", "message": message,
                                            "errorCode": 1, "errorLocation": None, "failureInfo": {}}, "query-1")


def test_sql_runs_as_role_user_and_caps_rows(client, idp, trino_returns):
    cursor, calls = trino_returns(rows=[[i] for i in range(data.SQL_MAX_ROWS + 5)])
    idp.sign_in(client)
    result = client.post("/api/sql", json={"sql": "  SELECT a FROM t;  "}).json()
    assert calls == [("operations_analyst", "Ops@Example.com")] and cursor.sql == "SELECT a FROM t"
    assert len(result["rows"]) == data.SQL_MAX_ROWS and result["truncated"] and cursor.cancelled
    assert result["columns"] == [{"name": "a", "type": "integer"}] and result["query_identity"] == "operations_analyst"


@pytest.mark.parametrize("name, status", [("PERMISSION_DENIED", 403), ("COLUMN_NOT_FOUND", 400)])
def test_sql_errors_keep_trinos_message(client, idp, trino_returns, name, status):
    trino_returns(error=trino_user_error(name, "Access Denied: Cannot select from columns [touchdown_peak_g]"))
    idp.sign_in(client)
    response = client.post("/api/sql", json={"sql": "SELECT touchdown_peak_g FROM x"})
    assert response.status_code == status
    assert response.json() == {"error": "Access Denied: Cannot select from columns [touchdown_peak_g]"}


def test_slow_sql_is_cancelled(client, idp, trino_returns, monkeypatch):
    monkeypatch.setattr(data, "SQL_SECONDS", 0.05)
    cursor, _ = trino_returns(delay=0.5)
    idp.sign_in(client)
    assert client.post("/api/sql", json={"sql": "SELECT 1"}).status_code == 408 and cursor.cancelled


def test_sql_needs_a_role(client, idp):
    assert client.post("/api/sql", json={"sql": "SELECT 1"}).status_code == 401
    idp.sign_in(client, email="stranger@example.com")
    assert client.post("/api/sql", json={"sql": "SELECT 1"}).status_code == 403


def test_plain_values_are_json_safe():
    assert data.plain(float("nan")) is None and data.plain(Decimal("1.5")) == 1.5
    assert data.plain(datetime(2022, 3, 22, 11, 13, 10, tzinfo=timezone.utc)) == "2022-03-22T11:13:10+00:00"
    assert data.plain([b"\x01", {"k": date(2022, 1, 2)}]) == ["01", {"k": "2022-01-02"}]


def test_sensors_align_on_whole_seconds(client, idp, monkeypatch):
    rows = [{"t": 0, "alt": 10.4, "ias": None, "gs": 1.04, "heading": -68.2031, "pitch": 2.81250, "roll": 0.17,
             "vrtg": 0.99609, "vrtg_max": 1.0},
            {"t": 2, "alt": float("nan"), "ias": 244.0, "gs": None, "heading": None, "pitch": None, "roll": None,
             "vrtg": None, "vrtg_max": None}]
    seen = []
    monkeypatch.setattr(data, "query", lambda sql, user, person, parameters=None: seen.append((user, parameters)) or rows)
    idp.sign_in(client)
    sensors = client.get("/api/flights/sensors?id=f1").json()
    assert seen == [("operations_analyst", ["f1", "f1", "f1"])]
    assert sensors["seconds"] == 3 and sensors["series"]["alt"] == [10.0, None, None]
    assert sensors["series"]["ias"] == [None, None, 244.0] and sensors["series"]["heading"][0] == -68.2


def test_catalog_groups_columns_by_table(client, idp, monkeypatch):
    monkeypatch.setattr(data, "query", lambda sql, user, person, parameters=None: [
        {"table_schema": "gold", "table_name": "flight_summary", "column_name": "flight_id", "data_type": "varchar"},
        {"table_schema": "gold", "table_name": "flight_summary", "column_name": "airborne_min", "data_type": "double"}])
    idp.sign_in(client)
    assert client.get("/api/catalog").json()["tables"] == {"iceberg.gold.flight_summary": [
        {"name": "flight_id", "type": "varchar"}, {"name": "airborne_min", "type": "double"}]}
