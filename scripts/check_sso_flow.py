"""End-to-end check of sign-in, role dashboards and Trino access for the running SSO stack.

python scripts/check_sso_flow.py

Signs in through the real Keycloak login form as every demo user, then checks that
each role gets its own dashboard, that the dashboard and the flight API return what
Trino returns for that role, and that signed-out, role-less, edited-token and
wrong-password requests are refused. Needs the stack from start_bi_demo.ps1.
"""
import base64
import html
import json
import re
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, build_opener

import trino

from bi_demo_settings import ROLES, TRINO_CERT, WEB_URL, read_secret, trino_connection


class BrowserLikePolicy(DefaultCookiePolicy):
    # Browsers treat http://localhost as a secure origin and send Keycloak's Secure cookies there.
    def return_ok_secure(self, cookie, request):
        return True


def browser():
    return build_opener(HTTPCookieProcessor(CookieJar(BrowserLikePolicy())))


def fetch(opener, url, data=None):
    try:
        with opener.open(url, data, timeout=60) as response:
            return response.status, response.geturl(), response.read().decode()
    except HTTPError as error:
        return error.code, url, error.read().decode()


def login_form_action(page):
    form = re.search(r'<form[^>]*id="kc-form-login"[^>]*>', page)
    return form and html.unescape(re.search(r'action="([^"]+)"', form.group()).group(1))


def sign_in(username, password):
    opener = browser()
    _, _, page = fetch(opener, WEB_URL + "/")
    action = login_form_action(page)
    assert action, "Opening the site did not lead to the Keycloak login form"
    status, final_url, _ = fetch(opener, action, urlencode({"username": username, "password": password}).encode())
    assert status == 200 and final_url.rstrip("/") == WEB_URL, f"{username}: sign-in ended at {final_url} ({status})"
    return opener


def as_trino(user, sql):
    connection = trino_connection(user)
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        connection.close()


def token_dashboard(embed_url):
    token = embed_url.split("/embed/dashboard/", 1)[1].split("#", 1)[0]
    payload = token.split(".")[1]
    return token, json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["resource"]["dashboard"]


def check_role_user(username, login, metabase):
    role = ROLES[login["role"]]
    opener = sign_in(username, login["password"])
    me = json.loads(fetch(opener, WEB_URL + "/api/me")[2])
    assert me["user"] == username and me["role"] == login["role"], me
    embed = json.loads(fetch(opener, WEB_URL + "/api/bi/embed")[2])
    token, dashboard_id = token_dashboard(embed["embed_url"])
    assert dashboard_id == read_secret("metabase-embed.json")["dashboards"][login["role"]], embed
    dashboard = json.loads(fetch(metabase, embed["embed_url"].split("/embed/")[0] + "/api/embed/dashboard/" + token)[2])
    assert role["label"] in dashboard["name"], dashboard["name"]
    card = next(c for c in dashboard["dashcards"] if (c.get("card") or {}).get("name") == "Flights in Gold")
    url = embed["embed_url"].split("/embed/")[0] + f"/api/embed/dashboard/{token}/dashcard/{card['id']}/card/{card['card_id']}"
    shown = json.loads(fetch(metabase, url)[2])["data"]["rows"][0][0]
    expected = as_trino(role["trino_user"], "SELECT count(*) FROM iceberg.gold.flight_summary")[0][0]
    assert shown == expected, f"{username}: dashboard shows {shown}, Trino returns {expected}"
    flights = json.loads(fetch(opener, WEB_URL + "/api/flights")[2])
    assert flights["total"] == as_trino(role["trino_user"], "SELECT count(*) FROM iceberg.silver.flights")[0][0]
    if login["role"] == "operations":
        assert {f["tail"] for f in flights["flights"]} == {"REDACTED"}, "Operations must see masked tails"
    print(f"PASS {username}: {role['label']} dashboard {dashboard_id}, {shown} Gold flight(s), "
          f"{flights['total']} Silver flight(s) as {role['trino_user']}", flush=True)
    return opener, token


def main():
    logins = read_secret("demo-logins.json")
    metabase = build_opener()
    tokens = {}
    for username, login in logins.items():
        if login["role"]:
            _, tokens[login["role"]] = check_role_user(username, login, metabase)

    # No role: signed in, but no dashboard and no flight data.
    opener = sign_in("norole.demo", logins["norole.demo"]["password"])
    assert json.loads(fetch(opener, WEB_URL + "/api/me")[2])["role"] is None
    assert fetch(opener, WEB_URL + "/api/bi/embed")[0] == 403 and fetch(opener, WEB_URL + "/api/flights")[0] == 403
    print("PASS norole.demo: signed in, but dashboard and flight API refused (403)", flush=True)

    # Sign-out ends both the site session and the Keycloak session.
    fetch(opener, WEB_URL + "/logout")
    assert fetch(opener, WEB_URL + "/api/me")[0] == 401
    assert login_form_action(fetch(opener, WEB_URL + "/")[2]), "After sign-out the site must ask for the password again"
    print("PASS sign-out: site session gone and Keycloak asks for the password again", flush=True)

    anonymous = browser()
    assert fetch(anonymous, WEB_URL + "/api/flights")[0] == 401 and fetch(anonymous, WEB_URL + "/api/bi/embed")[0] == 401
    print("PASS signed out: APIs answer 401", flush=True)

    # Editing the dashboard number inside a token keeps the old signature: Metabase refuses it.
    header, _, signature = tokens["operations"].split(".")
    payload = tokens["safety"].split(".")[1]
    status = fetch(metabase, "http://localhost:3002/api/embed/dashboard/" + f"{header}.{payload}.{signature}")[0]
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


if __name__ == "__main__":
    main()
