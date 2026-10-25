# QAR web client

React and TypeScript application served by the FastAPI backend. Google sign-in creates a server session; the browser never selects a Trino identity or receives the identity provider token.

All application pages use live services:

- **Flight Explorer**: flight recordings visible to the signed-in role, with search, filters and pagination.
- **Flight details**: recording metadata, flight summary, phases and detected events from Silver/Gold.
- **Sensor Playback**: actual Silver sensor arrays through the backend, synchronized by recording offset. Missing values remain gaps; no values are generated or interpolated. The backend selects the first sample in each second and the peak vertical acceleration for that second. Playback speed is literal (1x is one recorded second per second).
- **SQL Workspace**: authenticated backend queries to Trino, a live Silver/Gold catalog and session query history. Only SQL is submitted; the server chooses the role account and OPA enforces permissions.
- **Flight Reports**: a signed Metabase dashboard selected by the server for the session role.

The client contains no simulated identities, browser SQL/policy engine, mock server, static flight records or prototype-only routes.

## Run

From the repository root, rebuild the application image after changing the client:

```sh
docker compose -f docker-compose.app.yaml up -d --build backend
```

Open http://localhost:8766/. Restarting the backend clears its in-memory sessions, so sign in again after a rebuild.

For development, keep the backend stack running and start Vite from `client/`:

```sh
npm ci
npm run dev
```

Vite proxies `/api`, `/login`, `/callback`, `/logout` and `/metabase` to `QAR_BACKEND_URL` (default http://localhost:8766). Sign-in follows the real backend flow.

## Backend contract

| Route | Returns |
| --- | --- |
| `GET /api/me` | User and role from the authenticated session; 401 when signed out |
| `GET /api/flights` | Role-scoped Silver metadata; up to 1,000 flights |
| `GET /api/flights/detail?id=` | Metadata, available Gold metrics, phases and events |
| `GET /api/flights/sensors?id=` | One value per second from Silver sensor tables; absent values are null |
| `GET /api/catalog` | Visible Silver/Gold tables and column types |
| `POST /api/sql` | `{sql}` → server columns, rows, timing and query identity; up to 500 rows and 30 seconds |
| `GET /api/bi/embed` | Signed embed URL for the role dashboard |
| `GET /metabase` | Redirect to that signed dashboard |

401 responses return to sign-in. Denied queries retain their server error. Stop waiting aborts the browser request; server queries exceeding 30 seconds are cancelled automatically.

## Verify

From `client/`, run `npm test` and `npm run build` to check API contracts, sensor rendering calculations, types and bundling. From the repository root, `python scripts/check_workspace_api.py` checks the backend handlers against the live Trino/OPA stack with isolated test sessions. It does not automate Google login or add sessions to the running application.

The local Compose setup and its existing provisioning script names remain supported. A production client build does not deploy the system to a production hosting environment.
