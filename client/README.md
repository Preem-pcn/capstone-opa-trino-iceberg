# QAR web client

The QAR web app: React + TypeScript (Vite), ported from the v3 stakeholder prototype. The backend
(`backend/`) owns the sign-in and the session, so the browser never sees an identity token. Flight
Explorer and Gold Reports are live; Cockpit, SQL Workspace and the OPA fixtures keep their prototype data.

## Run

In the app stack (`docker-compose.app.yaml`) the backend image builds this folder and serves it at
http://localhost:8766/. No Node is needed on the host. After editing the client, rebuild the backend:

```sh
docker compose -f docker-compose.app.yaml up -d --build backend
```

For live editing, run the Vite dev server next to the stack:

```sh
npm install
npm run dev         # http://localhost:5173, proxies to the real backend: Google sign-in, real data
npm run dev:mock    # http://localhost:5173 without the stack: mock backend and made-up users
npm run build       # dist/
```

`npm run dev` sends `/api`, `/login`, `/callback`, `/logout` and `/metabase` to the backend
(`QAR_BACKEND_URL`, default http://localhost:8766). Google returns to the registered callback on
port 8766; the backend then sends the browser back to the dev server page you started from
(allowed by `DEV_ORIGINS` in `docker-compose.app.yaml`). The session cookie belongs to `localhost`,
so it works on both ports. The mock backend (`mock/backend.ts`) has made-up users `safety.demo`,
`ops.demo`, `eng.demo` and `norole.demo` with the stack's role filters and masks; its flight values
other than TG0341's Gold rows are placeholders.

## Backend contract

| Route | Returns |
| --- | --- |
| `GET /login`, `/callback`, `/logout` | Sign-in with the identity provider and sign-out (full-page redirects) |
| `GET /api/me` | `{user, name, role, role_label, scope, trino_user}`; `role` is null with no role or several roles. 401 when signed out |
| `GET /api/bi/embed` | `{embed_url, refresh_after_seconds, dashboard_id, role, role_label, query_identity}` for the session's role; 403 without a role |
| `GET /metabase` | Redirect to the same signed dashboard (opens in a new tab) |
| `GET /api/flights` | Silver flight metadata as the role's Trino user: `{flights, total, truncated, query_identity, source}` |
| `GET /api/flights/detail?id=` | `{flight, summary, phases, events, query_identity}`; 404 if the role cannot see the flight |

The signed embed token names one dashboard and nothing else. What each role sees is decided by
that dashboard's Trino connection user and OPA, not by anything the browser sends.

## Layout

- `src/session.tsx`: `/api/me` and the sign-in gate
- `src/state.tsx`: page state, the live flight list and per-flight detail cache, the simulated SQL runner
- `src/pages/Explorer.tsx`, `FlightDetail.tsx`: live Silver/Gold through the backend
- `src/pages/Reports.tsx`: the role's signed Metabase dashboard
- `src/lib/sqlEngine.ts`: browser policy simulation for the OPA fixture tables only; not enforcement
- `src/data/demo.ts`: v3 prototype data for the pages that are not live yet
