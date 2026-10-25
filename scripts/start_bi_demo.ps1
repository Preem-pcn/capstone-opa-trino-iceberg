param([switch]$CheckOnly, [switch]$NoWeb)

$ErrorActionPreference = 'Stop'
$biRoot = Split-Path -Parent $PSScriptRoot
Push-Location $biRoot
try {
    if (-not $CheckOnly) {
        & python scripts/init_bi_secrets.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local secrets in .secrets/.' }
        & docker compose -f docker-compose.bi-local.yaml up -d --wait --wait-timeout 300
        if ($LASTEXITCODE -ne 0) { throw 'The isolated capstone BI stack is not ready. Check its compose logs.' }
        & python -u scripts/load_bi_samples.py
        if ($LASTEXITCODE -ne 0) { throw 'Loading or checking the decoded sample data failed.' }
        & python scripts/setup_bi_demo.py
        if ($LASTEXITCODE -ne 0) { throw 'Metabase setup or verification failed.' }
        & python scripts/build_bi_page.py
        if ($LASTEXITCODE -ne 0) { throw 'Could not build the page from the v3 prototype.' }
    } else {
        & python scripts/load_bi_samples.py --check
        if ($LASTEXITCODE -ne 0) { throw 'Sample data verification failed.' }
        & python scripts/setup_bi_demo.py --check
        if ($LASTEXITCODE -ne 0) { throw 'Metabase setup or verification failed.' }
        & python scripts/check_sso_flow.py
        if ($LASTEXITCODE -ne 0) { throw 'The sign-in and role check failed.' }
    }
    if ($LASTEXITCODE -ne 0) { throw 'Metabase setup or verification failed.' }
    if (-not $CheckOnly -and -not $NoWeb) {
        $webReady = $false
        try {
            $webHealth = Invoke-RestMethod 'http://127.0.0.1:8766/api/bi/health' -TimeoutSec 5
            $webReady = $webHealth.service -eq 'qar-capstone-metabase-demo'
        } catch { }
        if (-not $webReady) {
            $pythonPath = (Get-Command python).Source
            $webScript = Join-Path $PSScriptRoot 'serve_bi_demo.py'
            Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"{0}"' -f $webScript)) -WorkingDirectory $biRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $biRoot '.secrets/bi-web.out.log') -RedirectStandardError (Join-Path $biRoot '.secrets/bi-web.err.log') | Out-Null
            for ($webAttempt = 0; $webAttempt -lt 10; $webAttempt++) {
                Start-Sleep -Seconds 1
                try {
                    $webHealth = Invoke-RestMethod 'http://127.0.0.1:8766/api/bi/health' -TimeoutSec 5
                    if ($webHealth.service -eq 'qar-capstone-metabase-demo') { $webReady = $true; break }
                } catch { }
            }
        }
        if (-not $webReady) { throw 'Could not open the capstone web demo on port 8766. Check .secrets/bi-web.err.log (running it outside Docker needs: pip install "pyjwt[crypto]").' }
        Write-Host 'Open CAPSTONE Gold Reports: http://localhost:8766/#gold'
        Write-Host 'Sign in as ops.demo, eng.demo, safety.demo or norole.demo. Passwords: .secrets/demo-logins.json'
    }
} finally {
    Pop-Location
}
