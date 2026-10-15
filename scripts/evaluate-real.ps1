param([string]$OutputDirectory = 'work/evaluations')
. "$PSScriptRoot/docker-common.ps1"
$outputDirectory = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$name = 'baseline-50-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,6) + '.json'
$remote = '/tmp/' + $name
Invoke-Docker compose cp scripts/evaluate_real.py api:/tmp/evaluate_real.py
& docker compose exec -T -e PYTHONPATH=/app api python /tmp/evaluate_real.py --base-url http://localhost:8000 --cases /app/samples/evaluation-50.json --output $remote
$evaluationExit = $LASTEXITCODE
# Failed quality checks still produce a report. A preflight failure produces none.
& docker compose exec -T api python -c "from pathlib import Path; import sys; sys.exit(0 if Path('$remote').is_file() else 1)"
if ($LASTEXITCODE -eq 0) { Invoke-Docker compose cp "api:$remote" (Join-Path $outputDirectory $name) }
if ($evaluationExit -ne 0) { throw 'Evaluation incomplete or quality checks failed; inspect the report. Mock mode is rejected before login.' }
Write-Output ('Evaluation report: ' + (Join-Path $outputDirectory $name))
