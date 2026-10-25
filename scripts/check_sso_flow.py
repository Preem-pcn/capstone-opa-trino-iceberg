"""Check sign-in and access rules of the running app stack (docker-compose.app.yaml).

python scripts/check_sso_flow.py

Signing in with Google is interactive, so it is not automated here. The sign-in logic itself
(token checks, state and nonce, email -> role) is covered by the backend's tests, which run in
`docker build -f backend/Dockerfile --target test .`. This script checks the deployed pieces:
the backend serves the client, signed-out requests are refused, /login hands the browser to the
provider correctly, forged callbacks and edited dashboard tokens are refused, and Trino accepts
only correct passwords.
"""
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import trino

from bi_demo_settings import TRINO_CERT, WEB_URL, embed_url, read_secret


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = build_opener(NoRedirect)


def fetch(url):
    try:
        with OPENER.open(Request(url), timeout=30) as response:
            return response.status, response.headers, response.read().decode()
    except HTTPError as error:
        return error.code, error.headers, error.read().decode()


def main():
    status, _, body = fetch(WEB_URL + "/api/bi/health")
    health = json.loads(body)
    assert status == 200 and health["service"] == "qar-backend" and health["client_ready"], health
    assert health["dashboards_configured"], "Dashboards are not set up: run scripts/setup_bi_demo.py"
    print("PASS backend is up, serves the React client and has the dashboard links", flush=True)

    for path in ["/api/me", "/api/flights", "/api/flights/detail?id=x", "/api/bi/embed"]:
        assert fetch(WEB_URL + path)[0] == 401, path
    status, headers, _ = fetch(WEB_URL + "/reports")
    assert status == 302 and headers["Location"] == "/login?next=%2Freports", (status, headers.get("Location"))
    print("PASS signed out: APIs answer 401 and pages send the browser to sign-in", flush=True)

    status, headers, _ = fetch(WEB_URL + "/login")
    if not health["sign_in_configured"]:
        assert status == 503, status
        print("SKIP sign-in redirect: fill in .secrets/oidc.env, then "
              "`docker compose -f docker-compose.app.yaml up -d backend`", flush=True)
    else:
        assert status == 302, status
        target = urlsplit(headers["Location"])
        query = parse_qs(target.query)
        assert query["redirect_uri"] == [WEB_URL + "/callback"] and query["response_type"] == ["code"], query
        assert query["code_challenge_method"] == ["S256"] and "openid" in query["scope"][0].split(), query
        cookie = headers["Set-Cookie"]
        assert "HttpOnly" in cookie and "Path=/callback" in cookie, cookie
        print(f"PASS /login sends the browser to {target.netloc} with this site's callback, PKCE and a state cookie",
              flush=True)
        # The right state from a browser that did not start the sign-in (no state cookie) is refused.
        assert fetch(WEB_URL + f"/callback?code=forged&state={query['state'][0]}")[0] == 400
        print("PASS a callback without the starting browser's state cookie is refused", flush=True)

    # Editing the dashboard number inside a token keeps the old signature: Metabase refuses it.
    embed = read_secret("metabase-embed.json")
    tokens = {role: embed_url(dashboard).split("/embed/dashboard/", 1)[1].split("#", 1)[0]
              for role, dashboard in embed["dashboards"].items()}
    header, _, signature = tokens["operations"].split(".")
    payload = tokens["safety"].split(".")[1]
    status = fetch(embed["metabase_url"].rstrip("/") + f"/api/embed/dashboard/{header}.{payload}.{signature}")[0]
    assert status == 400, status
    print("PASS edited embed token refused by Metabase", flush=True)

    ops_password = read_secret("trino-users.json")["operations_analyst"]
    for user, auth, refusal in [
            ("operations_analyst", trino.auth.BasicAuthentication("operations_analyst", "wrong"), trino.exceptions.HttpError),
            ("admin", None, trino.exceptions.HttpError),  # no password at all
            ("admin", trino.auth.BasicAuthentication("operations_analyst", ops_password), trino.exceptions.TrinoUserError)]:
        connection = trino.dbapi.connect(host="127.0.0.1", port=8443, user=user, http_scheme="https",
                                         verify=str(TRINO_CERT), auth=auth)
        try:
            connection.cursor().execute("SELECT 1")
        except refusal:
            continue
        raise AssertionError(f"Trino accepted a query as {user} that it must refuse")
    print("PASS Trino: wrong or missing password refused; a role login cannot act as admin", flush=True)
    print("Not automated: signing in with Google. Open " + WEB_URL + "/ and sign in with an account "
          "listed in .secrets/role-assignments.json.", flush=True)


if __name__ == "__main__":
    main()
