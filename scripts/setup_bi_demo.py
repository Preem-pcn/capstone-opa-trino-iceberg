"""Create/verify the local Metabase Gold dashboards, one per role, without changing lakehouse data.

Python standard library only. Credentials stay in ignored .secrets/ files.
Each role gets its own Trino connection (HTTPS, that role's Trino login), collection
and dashboard. Every chart therefore runs as the role's Trino user and OPA filters it.
"""

import argparse
import json
import os
import secrets
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from bi_demo_settings import ROLES, ROOT, embed_url, read_secret, write_json

AUTH_FILE = ROOT / ".secrets/metabase-demo.json"
STATE_FILE = ROOT / ".secrets/metabase-sso-state.json"
EMBED_FILE = ROOT / ".secrets/metabase-embed.json"
MANIFEST = json.loads((ROOT / "bi/dashboard.json").read_text(encoding="utf-8"))
PARAMETERS = [{"id": "flight_date", "name": "Flight date", "slug": "flight_date", "type": "date/single"},
              {"id": "aircraft_type", "name": "Aircraft type", "slug": "aircraft_type", "type": "category"}]


class Metabase:
    def __init__(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("This demo script only connects to local Metabase over HTTP.")
        self.base = base_url.rstrip("/")
        # Services bind IPv4 loopback; avoid Windows IPv6 connection fallback delays.
        self.api_base = self.base.replace("://localhost", "://127.0.0.1", 1)
        self.session = None

    def api(self, method, path, payload=None):
        headers = {"Content-Type": "application/json"}
        if self.session:
            headers["X-Metabase-Session"] = self.session
        request = Request(self.api_base + "/api" + path,
                          data=None if payload is None else json.dumps(payload).encode(),
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=180) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            # Do not dump connection details or request payloads containing passwords.
            message = exc.read().decode(errors="replace")
            for source in [AUTH_FILE, ROOT / ".secrets/trino-users.json"]:
                if source.exists():
                    for value in json.loads(source.read_text(encoding="utf-8")).values():
                        if isinstance(value, str) and len(value) > 10:
                            message = message.replace(value, "[redacted]")
            display_path = "/embed/dashboard/[signed-token]" if path.startswith("/embed/dashboard/") else path
            raise RuntimeError(f"Metabase {method} {display_path}: HTTP {exc.code}: {message[:1600]}") from None

    def login(self, allow_setup):
        props = self.api("GET", "/session/properties")
        setup_token = props.get("setup-token")
        if AUTH_FILE.exists():
            auth = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        elif setup_token and allow_setup:
            auth = {"email": "demo@qar.local", "password": secrets.token_urlsafe(24) + "aA1!"}
            # Persist before setup so an unknown HTTP outcome can be recovered by login.
            write_json(AUTH_FILE, auth)
        elif os.environ.get("METABASE_EMAIL") and os.environ.get("METABASE_PASSWORD"):
            auth = {"email": os.environ["METABASE_EMAIL"], "password": os.environ["METABASE_PASSWORD"]}
        else:
            raise RuntimeError("Metabase is already initialized. Provide METABASE_EMAIL and METABASE_PASSWORD, or restore .secrets/metabase-demo.json.")
        if setup_token:
            if not allow_setup:
                raise RuntimeError("Metabase has not been set up. Run without --check first.")
            self.api("POST", "/setup", {
                "token": setup_token,
                "user": {"first_name": "QAR", "last_name": "Demo", **auth},
                "prefs": {"site_name": "QAR Gold BI POC", "allow_tracking": False},
            })
        self.session = self.api("POST", "/session", {"username": auth["email"], "password": auth["password"]})["id"]


def cards_for(role):
    """Cards this role's dashboard gets: optional "roles" filter and per-role "layout" override."""
    return [{**card, **card.get("layout", {}).get(role, {})}
            for card in MANIFEST["cards"] if role in card.get("roles", ROLES)]


def dataset(database_id, card):
    query = (ROOT / "bi/queries" / card["query"]).read_text(encoding="utf-8")
    tags = {name: {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "qar-bi/" + name)),
                   "name": name, "display-name": title, "type": kind, "required": False}
            for name, title, kind in [("flight_date", "Flight date", "date"),
                                      ("aircraft_type", "Aircraft type", "text")]}
    return {"database": database_id, "type": "native", "native": {"query": query, "template-tags": tags}}


def connection(role):
    user = ROLES[role]["trino_user"]
    # The container trusts Trino's self-signed certificate mounted at /tls (see docker-compose.bi-local.yaml).
    return {"name": f"QAR Gold · {ROLES[role]['label']} ({user})", "engine": "starburst", "is_full_sync": False,
            "details": {"host": "trino", "port": 8443, "catalog": "iceberg", "schema": "gold",
                        "user": user, "password": read_secret("trino-users.json")[user], "ssl": True,
                        "additional-options": "SSLTrustStorePath=/tls/trino.crt", "prepared-optimized": True}}


def seed_role(client, role, state):
    info, saved = ROLES[role], state["roles"].setdefault(role, {"cards": {}})
    if saved.get("database_id"):
        client.api("PUT", f'/database/{saved["database_id"]}', connection(role))
    else:
        saved["database_id"] = client.api("POST", "/database", connection(role))["id"]
        write_json(STATE_FILE, state)
    if not saved.get("collection_id"):
        saved["collection_id"] = client.api("POST", "/collection", {
            "name": f"QAR · {info['label']}", "description": MANIFEST["description"], "color": "#509EE3"})["id"]
        write_json(STATE_FILE, state)
    name = f'{MANIFEST["name"]} · {info["label"]}'
    if not saved.get("dashboard_id"):
        saved["dashboard_id"] = client.api("POST", "/dashboard", {
            "name": name, "description": MANIFEST["description"], "collection_id": saved["collection_id"]})["id"]
        write_json(STATE_FILE, state)
    cards = cards_for(role)
    for card in cards:
        body = {"name": card["name"], "display": card["display"],
                "description": f"Runs as Trino user {info['trino_user']}; OPA filters and masks the result.",
                "collection_id": saved["collection_id"], "dataset_query": dataset(saved["database_id"], card),
                "visualization_settings": card["settings"]}
        existing_id = saved["cards"].get(card["key"])
        result = client.api("PUT" if existing_id else "POST", f"/card/{existing_id}" if existing_id else "/card", body)
        saved["cards"][card["key"]] = result["id"]
        write_json(STATE_FILE, state)
        print(f"Saved {role}: {card['key']}", flush=True)
    client.api("PUT", f'/dashboard/{saved["dashboard_id"]}', {
        "name": name, "description": MANIFEST["description"], "parameters": PARAMETERS})
    # Preserve server dashcard IDs on reruns rather than accumulating duplicates.
    existing = client.api("GET", f'/dashboard/{saved["dashboard_id"]}')
    previous = {c.get("card_id"): c["id"] for c in existing.get("dashcards", [])}
    intro = f'{MANIFEST["intro"]} · {info["label"]}\n\nTrino user `{info["trino_user"]}` · {info["scope"]}'
    dashcards = [{"id": previous.get(None, -1), "card_id": None, "row": 0, "col": 0,
                  "size_x": 24, "size_y": 2, "parameter_mappings": [],
                  "visualization_settings": {"text": intro, "virtual_card": {"display": "text"}}}]
    for index, card in enumerate(cards, start=2):
        card_id = saved["cards"][card["key"]]
        dashcards.append({"id": previous.get(card_id, -index), "card_id": card_id,
                          **{k: card[k] for k in ["row", "col", "size_x", "size_y"]},
                          "visualization_settings": {},
                          "parameter_mappings": [{"parameter_id": p["id"], "card_id": card_id,
                                                  "target": ["variable", ["template-tag", p["id"]]]}
                                                 for p in PARAMETERS]})
    client.api("PUT", f'/dashboard/{saved["dashboard_id"]}/cards', {"cards": dashcards})


def seed(client):
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"roles": {}}
    for role in ROLES:
        seed_role(client, role, state)
    return state


def query_card(client, card_id, parameters=None):
    parameters = [dict(p, id=str(uuid.uuid5(uuid.NAMESPACE_URL, "qar-bi/" + p["target"][1][1])))
                  for p in (parameters or [])]
    result = client.api("POST", f"/card/{card_id}/query", {"parameters": parameters or [], "ignore_cache": True})
    if result.get("status") != "completed":
        raise RuntimeError(f"Card {card_id} query failed: {result.get('error', result.get('status'))}")
    return result["data"]["rows"]


def verify(client, state):
    for role, info in ROLES.items():
        saved = state["roles"][role]
        result = client.api("POST", "/dataset", {"database": saved["database_id"], "type": "native",
                                                "native": {"query": "SELECT current_user"}})
        if result.get("status") != "completed" or result["data"]["rows"] != [[info["trino_user"]]]:
            raise RuntimeError(f"Metabase is not querying Trino as {info['trino_user']} for {role}")
        dashboard = client.api("GET", f'/dashboard/{saved["dashboard_id"]}')
        if len([c for c in dashboard.get("dashcards", []) if c.get("card_id")]) != len(cards_for(role)):
            raise RuntimeError(f"The {role} dashboard does not contain all expected cards.")
        for card in cards_for(role):
            query_card(client, saved["cards"][card["key"]])
        flights = query_card(client, saved["cards"]["flight_count"])[0][0]
        print(f"PASS {role}: Trino user {info['trino_user']}, {len(cards_for(role))} cards, {flights} flight(s)", flush=True)
    # Filters: the Safety dashboard sees every flight, so test both filter paths there.
    cards = state["roles"]["safety"]["cards"]
    summary_rows = query_card(client, cards["flight_summary"])
    if not summary_rows:
        raise RuntimeError("Gold contains no flight summaries; no sample data was fabricated.")
    aircraft_type = summary_rows[0][2]
    filtered = query_card(client, cards["flight_count"], [{
        "type": "category", "target": ["variable", ["template-tag", "aircraft_type"]], "value": aircraft_type}])
    if not filtered or filtered[0][0] < 1:
        raise RuntimeError("Aircraft filter failed to select existing sample data.")
    date_filtered = query_card(client, cards["flight_count"], [{
        "type": "date/single", "target": ["variable", ["template-tag", "flight_date"]], "value": summary_rows[0][0]}])
    if not date_filtered or date_filtered[0][0] < 1:
        raise RuntimeError("Flight-date filter failed to select existing sample data.")
    no_match = query_card(client, cards["flight_count"], [{
        "type": "category", "target": ["variable", ["template-tag", "aircraft_type"]], "value": "__NO_MATCH_QAR_DEMO__"}])
    if no_match != [[0]]:
        raise RuntimeError("No-match filter did not return zero flights.")
    print("PASS aircraft/date filters and no-match result", flush=True)
    print(f"Metabase admin: {client.base} (login in .secrets/metabase-demo.json; do not commit/share it)", flush=True)


def enable_embed(client, state):
    current = json.loads(EMBED_FILE.read_text(encoding="utf-8")) if EMBED_FILE.exists() else {}
    settings = {item["key"]: item.get("value") for item in client.api("GET", "/setting")}
    secret = current.get("secret") or settings.get("embedding-secret-key") or secrets.token_hex(32)
    if not isinstance(secret, str) or len(secret) != 64:
        raise RuntimeError("An existing embedding secret could not be read; refusing to replace it.")
    dashboards = {role: saved["dashboard_id"] for role, saved in state["roles"].items()}
    write_json(EMBED_FILE, {"metabase_url": client.base, "secret": secret, "dashboards": dashboards})
    client.api("PUT", "/setting/embedding-secret-key", {"value": secret})
    client.api("PUT", "/setting/enable-embedding-static", {"value": True})
    client.api("PUT", "/setting/report-timezone", {"value": "UTC"})
    for dashboard_id in dashboards.values():
        client.api("PUT", f"/dashboard/{dashboard_id}", {
            "enable_embedding": True,
            "embedding_params": {"flight_date": "enabled", "aircraft_type": "enabled"}})
    print("Enabled signed embedding for the role dashboards only.", flush=True)


def verify_embed(client, state):
    anonymous = Metabase(client.base)
    tokens = {}
    for role, saved in state["roles"].items():
        tokens[role] = embed_url(saved["dashboard_id"]).split("/embed/dashboard/", 1)[1].split("#", 1)[0]
        if anonymous.api("GET", "/embed/dashboard/" + tokens[role]).get("id") != saved["dashboard_id"]:
            raise RuntimeError(f"Signed embed for {role} returned an unexpected dashboard.")
    # A viewer who edits the token to open another role's dashboard keeps the old signature: rejected.
    header, _, signature = tokens["operations"].split(".")
    _, payload, _ = tokens["safety"].split(".")
    try:
        anonymous.api("GET", f"/embed/dashboard/{header}.{payload}.{signature}")
    except RuntimeError:
        pass
    else:
        raise RuntimeError("A token with another role's dashboard and a stale signature was accepted.")
    print("PASS signed dashboard per role and rejected an edited token", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:3002")
    parser.add_argument("--check", action="store_true", help="Verify the existing demo without updating it")
    args = parser.parse_args()
    client = Metabase(args.url)
    for attempt in range(12):
        try:
            health = client.api("GET", "/health")
            if health.get("status") == "ok":
                break
        except (URLError, RuntimeError):
            if attempt == 11:
                raise RuntimeError("Metabase is not ready at " + client.base) from None
        print("Waiting for Metabase health...", flush=True)
        time.sleep(5)
    client.login(allow_setup=not args.check)
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if args.check else seed(client)
    verify(client, state)
    if not args.check:
        enable_embed(client, state)
    verify_embed(client, state)


if __name__ == "__main__":
    main()
