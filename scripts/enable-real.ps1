param([ValidateRange(60, 7200)][int]$TimeoutSeconds = 1800)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
foreach ($bin in @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin", 'C:\Program Files\Docker\Docker\resources\bin')) {
    if (Test-Path -LiteralPath (Join-Path $bin 'docker.exe')) { $env:PATH = $bin + ';' + $env:PATH; break }
}
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE); inspect service logs." }
}
$path = Join-Path $PWD '.env'
$content = [IO.File]::ReadAllText($path)
if ($content -notmatch '(?m)^LLM_API_KEY=\S+') { throw 'Fill LLM_API_KEY in local .env first; never paste it into chat.' }
Invoke-Docker compose --profile bge up -d --wait --wait-timeout $TimeoutSeconds embedding
# Probe an isolated process before changing the active API/worker configuration.
Invoke-Docker compose run --rm --no-deps -e MODEL_MODE=real api python -m app.model_check --online
$updated = [regex]::Replace($content, '(?m)^MODEL_MODE=.*$', 'MODEL_MODE=real')
$updated = [regex]::Replace($updated, '(?m)^COMPOSE_PROFILES=.*$', 'COMPOSE_PROFILES=bge')
try {
    [IO.File]::WriteAllText($path, $updated, (New-Object Text.UTF8Encoding $false))
    Invoke-Docker compose up -d --build --wait --wait-timeout $TimeoutSeconds api worker scheduler gateway
    Invoke-Docker compose exec -T api python -m app.cli reindex
} catch {
    # Re-publish the original index if a partial reindex happened before a failure.
    [IO.File]::WriteAllText($path, $content, (New-Object Text.UTF8Encoding $false))
    & docker compose up -d --wait api worker scheduler gateway
    if ($LASTEXITCODE -eq 0) { & docker compose exec -T api python -m app.cli reindex }
    throw
}
Write-Output 'Real providers verified and documents reindexed. Run scripts/evaluate_real.py with samples/evaluation-50.json next.'
