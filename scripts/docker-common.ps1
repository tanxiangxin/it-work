$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
foreach ($bin in @("$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin", 'C:\Program Files\Docker\Docker\resources\bin')) {
    if (Test-Path -LiteralPath (Join-Path $bin 'docker.exe')) { $env:PATH = $bin + ';' + $env:PATH; break }
}
function Invoke-Docker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
