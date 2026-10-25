"""Check SQL API handlers against the running Trino/OPA app stack.

Run from the repository root with backend and test dependencies installed:
    python scripts/check_workspace_api.py

Uses isolated in-process FastAPI test sessions, not a real Google sign-in.
No routes, credentials or sessions are added to the running application.
"""
import os
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
os.environ.update({
    'SECRETS_DIR': str(root / '.secrets'), 'ROLES_FILE': str(root / 'bi/roles.json'),
    'CLIENT_DIST': str(root / 'client/dist'), 'TRINO_HOST': '127.0.0.1', 'TRINO_PORT': '8443',
    'PUBLIC_URL': 'http://localhost:8766',
})
sys.path.insert(0, str(root / 'backend'))
from fastapi.testclient import TestClient
from app import auth, main, settings

checks = 0
def passed(name):
    global checks
    checks += 1
    print('PASS', name, flush=True)

def sql(client, statement, status=200, **extra):
    response = client.post('/api/sql', json={'sql': statement, **extra})
    assert response.status_code == status, (response.status_code, response.json())
    return response.json()

with TestClient(main.app, base_url='http://localhost:8766') as client:
    sql(client, 'SELECT current_user', 401)
    passed('signed-out SQL is refused')
    for role in ['engineering', 'operations', 'safety']:
        user = settings.ROLES[role]['trino_user']
        sid = auth.STORE.create(auth.Session('workspace-integration-test', 'Test', role, '', time.time() + 600))
        client.cookies.set(main.SESSION_COOKIE, sid)
        identity = sql(client, 'SELECT current_user', role='admin', user='admin', trino_user='admin')
        assert identity['rows'] == [[user]] and identity['query_identity'] == user
        passed(f'{role}: session chooses Trino account; client identity overrides ignored')
        catalog = client.get('/api/catalog')
        assert catalog.status_code == 200, catalog.json()
        assert catalog.json()['query_identity'] == user
        assert all(name.split('.')[1] in ('silver', 'gold') for name in catalog.json()['tables'])
        columns = [v['name'] for v in catalog.json()['tables']['iceberg.gold.flight_summary']]
        assert ('touchdown_peak_g' in columns) == (role != 'operations')
        passed(f'{role}: live catalog respects denied columns')
        inventory = client.get('/api/flights')
        assert inventory.status_code == 200, inventory.json()
        flight_id = inventory.json()['flights'][0]['flight_id']
        sensors = client.get('/api/flights/sensors', params={'id': flight_id})
        assert sensors.status_code == 200, sensors.json()
        sensor_data = sensors.json()
        assert sensor_data['query_identity'] == user and sensor_data['seconds'] > 0
        assert all(len(values) == sensor_data['seconds'] for values in sensor_data['series'].values())
        assert any(value is not None for value in sensor_data['series']['alt'])
        passed(f'{role}: recorded sensors load through the backend with aligned time offsets')
        rows = sql(client, 'SELECT tail, flight_no, origin, destination FROM iceberg.silver.flights')['rows']
        assert rows
        if role == 'engineering':
            assert all(row[0] == 'HS-THJ' and row[1:] == ['REDACTED'] * 3 for row in rows)
            assert sql(client, "SELECT count(*) FROM iceberg.silver.flights WHERE tail <> 'HS-THJ'")['rows'] == [[0]]
            passed('engineering: real rows filtered to HS-THJ; flight number and route masked')
        if role == 'operations':
            assert all(row[0] == 'REDACTED' and 'VTBS' in row[2:] for row in rows)
            sql(client, 'SELECT touchdown_peak_g FROM iceberg.gold.flight_summary', 403)
            passed('operations: real rows scoped to VTBS; tail masked; touchdown g denied')
        if role == 'safety':
            rows = sql(client, 'SELECT recording, source_file FROM iceberg.silver.flights')['rows']
            assert all(row == ['REDACTED', 'REDACTED'] for row in rows)
            passed('safety: recording and source file masked')
        sql(client, 'SELECT * FROM iceberg.opa_demo_silver.unlisted_demo', 403)
        passed(f'{role}: unlisted table refused by real OPA')
    values = sql(client, "SELECT CAST(NULL AS VARCHAR) AS missing, true AS enabled, ARRAY[1, 2] AS samples, MAP(ARRAY['a'], ARRAY[1]) AS attributes")
    assert values['rows'] == [[None, True, [1, 2], {'a': 1}]], values
    passed('real JSON null, boolean, array and map result values')
    limited = sql(client, 'SELECT n FROM UNNEST(sequence(1, 501)) AS t(n)')
    assert limited['truncated'] and len(limited['rows']) == 500
    passed('real SQL result is capped at 500 rows')
    sql(client, 'SELECT definitely_missing_column FROM iceberg.silver.flights', 400)
    passed('real Trino SQL errors retain HTTP 400')
print(f'{checks} live API/Trino/OPA checks passed', flush=True)
