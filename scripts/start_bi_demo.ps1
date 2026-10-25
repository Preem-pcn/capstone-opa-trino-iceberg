param([switch]$CheckOnly)

# Start or check the app stack (docker-compose.app.yaml). start_bi_demo.sh does the same on macOS/Linux.
$ErrorActionPreference = 'Stop'
$biRoot = Split-Path -Parent $PSScriptRoot
Push-Location $biRoot
try {
    if ($CheckOnly) {
        & python scripts/load_bi_samples.py --check
        if ($LASTEXITCODE -ne 0) { throw 'Sample data verification failed.' }
        & python scripts/load_opa_fixtures.py --check
        if ($LASTEXITCODE -ne 0) { throw 'OPA fixture verification failed.' }
        & python scripts/setup_bi_demo.py --check
        if ($LASTEXITCODE -ne 0) { throw 'Metabase verification failed.' }
        & docker build -f backend/Dockerfile --target test -q . | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed (docker build -f backend/Dockerfile --target test .).' }
        Write-Host 'PASS backend tests (sign-in, roles, data access, static files)'
        & python scripts/check_sso_flow.py
        if ($LASTEXITCODE -ne 0) { throw 'The sign-in and access check failed.' }
        return
    }
    & python scripts/init_bi_secrets.py
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local secrets in .secrets/.' }
    & docker compose -f docker-compose.app.yaml up -d --build --wait --wait-timeout 300 --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw 'The app stack is not ready. Check: docker compose -f docker-compose.app.yaml logs' }
    & python -u scripts/load_bi_samples.py
    if ($LASTEXITCODE -ne 0) { throw 'Loading or checking the decoded sample data failed.' }
    & python scripts/load_opa_fixtures.py
    if ($LASTEXITCODE -ne 0) { throw 'Creating or checking the OPA fixtures failed.' }
    & python scripts/setup_bi_demo.py
    if ($LASTEXITCODE -ne 0) { throw 'Metabase setup or verification failed.' }
    $health = Invoke-RestMethod 'http://127.0.0.1:8766/api/bi/health' -TimeoutSec 5
    if (-not $health.sign_in_configured) {
        Write-Host 'Sign-in is not configured yet: fill in .secrets/oidc.env (Google OAuth client) and'
        Write-Host '.secrets/role-assignments.json, then run: docker compose -f docker-compose.app.yaml up -d backend'
    }
    Write-Host 'Open QAR Flight Analytics: http://localhost:8766/'
} finally {
    Pop-Location
}
