param([switch]$Test, [ValidateRange(60, 7200)][int]$StartupTimeoutSeconds = 180)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerPath = if ($dockerCommand) { $dockerCommand.Source } else { $null }
if (!$dockerPath) {
    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe",
        'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    )) {
        if (Test-Path -LiteralPath $candidate) { $dockerPath = $candidate; break }
    }
}
if (!$dockerPath) { throw 'Docker Desktop is not installed. Install it and start its Linux container engine first.' }
$env:PATH = (Split-Path -Parent $dockerPath) + [IO.Path]::PathSeparator + $env:PATH
if (!(Test-Path -LiteralPath '.env')) { throw 'Missing .env. Generate it with scripts/init_env.py first.' }
# Desktop's Linux engine has its own pipe. Respect explicitly configured remote engines.
$dockerOptions = @()
if (!$env:DOCKER_HOST -and !$env:DOCKER_CONTEXT) {
    $currentContext = & $dockerPath context show
    $contexts = & $dockerPath context ls --format '{{.Name}}'
    if ($currentContext -eq 'default' -and $contexts -contains 'desktop-linux') {
        $dockerOptions = @('--context', 'desktop-linux')
    }
}
function Invoke-Docker {
    & $dockerPath @dockerOptions @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
$engineType = & $dockerPath @dockerOptions info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is unavailable. Start Docker Desktop and wait for it to be ready.' }
if ($engineType -ne 'linux') { throw 'Switch Docker Desktop to Linux containers first.' }
Invoke-Docker compose up -d --build --wait --wait-timeout $StartupTimeoutSeconds
Invoke-Docker compose exec -T api python -m app.cli seed
Invoke-Docker compose exec -T api python -m app.cli seed-documents
if ($Test) { Invoke-Docker compose --profile test run --build --rm tests }
Invoke-Docker compose ps
$gatewayReady = $false
for ($attempt = 0; $attempt -lt 12; $attempt++) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:8080/api/v1/health/ready' -TimeoutSec 5
        if ($response.StatusCode -eq 200) { $gatewayReady = $true; break }
    } catch { }
    Start-Sleep -Seconds 2
}
if (!$gatewayReady) { throw 'Gateway readiness failed. Check compose logs gateway api.' }
Write-Host 'Ready: http://localhost:8080'
Write-Host 'Student: student@example.test; Admin: admin@example.test. Initial passwords come from .env; existing database passwords are preserved.'
