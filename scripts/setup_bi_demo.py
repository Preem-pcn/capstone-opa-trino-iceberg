"""Create/verify the local Metabase Gold demo without changing lakehouse data.

Python standard library only. Credentials stay in ignored .secrets/ files.
All charts query Gold as safety_analyst using this repository local HTTP/OPA setup.
"""

import argparse
import json
import os
import secrets
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
AUTH_FILE = ROOT / ".secrets/metabase-demo.json"
STATE_FILE = ROOT / ".secrets/metabase-demo-state.json"
MANIFEST = json.loads((ROOT / "bi/dashboard.json").read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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
            for source in [AUTH_FILE, ROOT / ".secrets/users.json"]:
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


def dataset(database_id, card):
    query = (ROOT / "bi/queries" / card["query"]).read_text(encoding="utf-8")
    tags = {name: {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "qar-bi/" + name)),
                   "name": name, "display-name": title, "type": kind, "required": False}
            for name, title, kind in [("flight_date", "Flight date", "date"),
                                      ("aircraft_type", "Aircraft type", "text")]}
    return {"database": database_id, "type": "native", "native": {"query": query, "template-tags": tags}}


def seed(client):
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {"cards": {}}
    connection = {"name": "Capstone Gold - Trino 8083 (safety_analyst)",
                  "engine": "starburst", "is_full_sync": False,
                  "details": {"host": "trino", "port": 8080, "catalog": "iceberg", "schema": "gold",
                              "user": "safety_analyst", "ssl": False, "prepared-optimized": True}}
    if not state.get("database_id"):
        state["database_id"] = client.api("POST", "/database", connection)["id"]
        write_json(STATE_FILE, state)
    if not state.get("collection_id"):
        state["collection_id"] = client.api("POST", "/collection", {
            "name": "QAR Gold BI POC", "description": MANIFEST["description"], "color": "#509EE3"})["id"]
        write_json(STATE_FILE, state)
    if not state.get("dashboard_id"):
        state["dashboard_id"] = client.api("POST", "/dashboard", {
            "name": MANIFEST["name"], "description": MANIFEST["description"],
            "collection_id": state["collection_id"]})["id"]
        write_json(STATE_FILE, state)
    for card in MANIFEST["cards"]:
        body = {"name": card["name"], "display": card["display"],
                "description": "POC: existing Gold data through capstone Trino as safety_analyst; draft metric for discussion.",
                "collection_id": state["collection_id"], "dataset_query": dataset(state["database_id"], card),
                "visualization_settings": card["settings"]}
        existing_id = state["cards"].get(card["key"])
        saved = client.api("PUT" if existing_id else "POST", f"/card/{existing_id}" if existing_id else "/card", body)
        state["cards"][card["key"]] = saved["id"]
        write_json(STATE_FILE, state)
        print("Saved:", card["key"], flush=True)
    parameters = [{"id": "flight_date", "name": "Flight date", "slug": "flight_date", "type": "date/single"},
                  {"id": "aircraft_type", "name": "Aircraft type", "slug": "aircraft_type", "type": "category"}]
    client.api("PUT", f'/dashboard/{state["dashboard_id"]}', {
        "name": MANIFEST["name"], "description": MANIFEST["description"], "parameters": parameters})
    # Preserve server dashcard IDs on reruns rather than accumulating duplicates.
    existing = client.api("GET", f'/dashboard/{state["dashboard_id"]}')
    previous = {c.get("card_id"): c["id"] for c in existing.get("dashcards", [])}
    dashcards = [{"id": previous.get(None, -1), "card_id": None, "row": 0, "col": 0,
                  "size_x": 24, "size_y": 3, "parameter_mappings": [],
                  "visualization_settings": {"text": MANIFEST["intro"], "virtual_card": {"display": "text"}}}]
    for index, card in enumerate(MANIFEST["cards"], start=2):
        card_id = state["cards"][card["key"]]
        dashcards.append({"id": previous.get(card_id, -index), "card_id": card_id,
                          **{k: card[k] for k in ["row", "col", "size_x", "size_y"]},
                          "visualization_settings": {},
                          "parameter_mappings": [{"parameter_id": p["id"], "card_id": card_id,
                                                  "target": ["variable", ["template-tag", p["id"]]]}
                                                 for p in parameters]})
    client.api("PUT", f'/dashboard/{state["dashboard_id"]}/cards', {"cards": dashcards})
    return state


def query_card(client, card_id, parameters=None):
    parameters = [dict(p, id=str(uuid.uuid5(uuid.NAMESPACE_URL, "qar-bi/" + p["target"][1][1])))
                  for p in (parameters or [])]
    result = client.api("POST", f"/card/{card_id}/query", {"parameters": parameters or [], "ignore_cache": True})
    if result.get("status") != "completed":
        raise RuntimeError(f"Card {card_id} query failed: {result.get('error', result.get('status'))}")
    return result["data"]["rows"]


def verify(client, state):
    dashboard = client.api("GET", f'/dashboard/{state["dashboard_id"]}')
    chart_cards = [c for c in dashboard.get("dashcards", []) if c.get("card_id")]
    if len(chart_cards) != len(MANIFEST["cards"]):
        raise RuntimeError("Dashboard does not contain all expected cards.")
    for card in MANIFEST["cards"]:
        rows = query_card(client, state["cards"][card["key"]])
        print(f'PASS {card["key"]}: {len(rows)} result row(s)', flush=True)
        if card["key"] == "flight_count":
            if not rows or rows[0][0] == 0:
                raise RuntimeError("Gold contains no flight summaries; no sample data was fabricated.")
            print(f'Gold flight count: {rows[0][0]}', flush=True)
    summary_rows = query_card(client, state["cards"]["flight_summary"])
    aircraft_type = summary_rows[0][2]
    # Positive filter path, then no-match path, using the same template tags as the dashboard.
    filtered = query_card(client, state["cards"]["flight_count"], [{
        "type": "category", "target": ["variable", ["template-tag", "aircraft_type"]], "value": aircraft_type}])
    if not filtered or filtered[0][0] < 1:
        raise RuntimeError("Aircraft filter failed to select existing sample data.")
    date_filtered = query_card(client, state["cards"]["flight_count"], [{
        "type": "date/single", "target": ["variable", ["template-tag", "flight_date"]], "value": summary_rows[0][0]}])
    if not date_filtered or date_filtered[0][0] < 1:
        raise RuntimeError("Flight-date filter failed to select existing sample data.")
    no_match = query_card(client, state["cards"]["flight_count"], [{
        "type": "category", "target": ["variable", ["template-tag", "aircraft_type"]], "value": "__NO_MATCH_QAR_DEMO__"}])
    if no_match != [[0]]:
        raise RuntimeError("No-match filter did not return zero flights.")
    print("PASS aircraft/date filters and no-match result", flush=True)
    print(f'Dashboard: {client.base}/dashboard/{state["dashboard_id"]}', flush=True)
    print("Local login: .secrets/metabase-demo.json (do not commit/share this file)", flush=True)


def enable_embed(client, state):
    from serve_bi_demo import CONFIG
    current = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    settings = {item["key"]: item.get("value") for item in client.api("GET", "/setting")}
    secret = current.get("secret") or settings.get("embedding-secret-key") or secrets.token_hex(32)
    if not isinstance(secret, str) or len(secret) != 64:
        raise RuntimeError("An existing embedding secret could not be read; refusing to replace it.")
    write_json(CONFIG, {"metabase_url": client.base, "dashboard_id": state["dashboard_id"], "secret": secret})
    client.api("PUT", "/setting/embedding-secret-key", {"value": secret})
    client.api("PUT", "/setting/enable-embedding-static", {"value": True})
    client.api("PUT", "/setting/report-timezone", {"value": "UTC"})
    client.api("PUT", f'/dashboard/{state["dashboard_id"]}', {
        "enable_embedding": True,
        "embedding_params": {"flight_date": "enabled", "aircraft_type": "enabled"}})
    print("Enabled signed embedding for the QAR Gold dashboard only.", flush=True)


def verify_embed(client, state):
    from serve_bi_demo import embed_info
    token = embed_info()["embed_url"].split("/embed/dashboard/", 1)[1].split("#", 1)[0]
    anonymous = Metabase(client.base)
    dashboard = anonymous.api("GET", "/embed/dashboard/" + token)
    if dashboard.get("id") != state["dashboard_id"]:
        raise RuntimeError("Signed embed returned an unexpected dashboard.")
    # Use an unauthenticated client to ensure a tampered token cannot load the dashboard.
    unsigned, signature = token.rsplit(".", 1)
    tampered = unsigned + "." + ("a" if signature[0] != "a" else "b") + signature[1:]
    try:
        anonymous.api("GET", "/embed/dashboard/" + tampered)
    except RuntimeError:
        pass
    else:
        raise RuntimeError("A tampered embedding token was accepted.")
    print("PASS signed dashboard metadata and rejected tampered token", flush=True)


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
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
