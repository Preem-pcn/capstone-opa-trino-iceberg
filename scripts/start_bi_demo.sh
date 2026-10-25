#!/usr/bin/env bash
# Start or check the app stack (docker-compose.app.yaml). macOS/Linux counterpart of start_bi_demo.ps1.
#
#   scripts/start_bi_demo.sh               # secrets, stack (builds the backend image), sample data, Metabase
#   scripts/start_bi_demo.sh --check-only  # data and Metabase checks, backend tests, sign-in and access rules
#
# PYTHON picks the interpreter with the loader's packages (pyarrow, pyiceberg, trino), e.g.
#   PYTHON="conda run -n qar python" scripts/start_bi_demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
COMPOSE="docker compose -f docker-compose.app.yaml"

check_only=false
for arg in "$@"; do
  case $arg in
    --check-only) check_only=true ;;
    *) echo "Unknown option: $arg (use --check-only)" >&2; exit 2 ;;
  esac
done

if $check_only; then
  $PY scripts/load_bi_samples.py --check
  $PY scripts/load_opa_fixtures.py --check
  $PY scripts/setup_bi_demo.py --check
  docker build -f backend/Dockerfile --target test -q . >/dev/null
  echo "PASS backend tests (sign-in, roles, data access, static files)"
  $PY scripts/check_sso_flow.py
  exit 0
fi

$PY scripts/init_bi_secrets.py
$COMPOSE up -d --build --wait --wait-timeout 300 --remove-orphans
$PY -u scripts/load_bi_samples.py
$PY scripts/load_opa_fixtures.py
$PY scripts/setup_bi_demo.py

if ! health=$(curl -fsS http://127.0.0.1:8766/api/bi/health); then
  echo "The backend is not answering on port 8766. Check: $COMPOSE logs backend" >&2
  exit 1
fi
case $health in
  *'"sign_in_configured":false'*)
    echo "Sign-in is not configured yet: fill in .secrets/oidc.env (Google OAuth client) and"
    echo ".secrets/role-assignments.json, then run: $COMPOSE up -d backend" ;;
esac
echo "Open QAR Flight Analytics: http://localhost:8766/"
