param([Parameter(Mandatory=$true)][string]$BackupDirectory)
. "$PSScriptRoot/docker-common.ps1"
$backupDirectory = (Resolve-Path -LiteralPath $BackupDirectory).Path
$checksums = Get-Content -Raw -LiteralPath (Join-Path $backupDirectory 'checksums.json') | ConvertFrom-Json
foreach ($name in @('campus.dump','files.tar.gz','manifest.json')) {
    if ((Get-FileHash -LiteralPath (Join-Path $backupDirectory $name) -Algorithm SHA256).Hash -ne $checksums.$name) { throw "Backup checksum failed: $name" }
}
# A unique Compose project gives every restored service/volume a separate name.
# No public gateway, worker or scheduler is started during the drill.
$project = 'campus-restore-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$options = @('compose','--project-name',$project,'--file',(Join-Path $ProjectRoot 'compose.yaml'))
Write-Output "Isolated restore project: $project"
try {
    Invoke-Docker @options up -d --wait postgres redis
    Invoke-Docker @options cp "$backupDirectory/campus.dump" postgres:/tmp/campus.dump
    Invoke-Docker @options exec -T postgres pg_restore -U campus -d campus --exit-on-error /tmp/campus.dump
    Invoke-Docker @options run --rm --no-deps --build --volume "${backupDirectory}:/backup:ro" api python -c "import tarfile; archive=tarfile.open('/backup/files.tar.gz'); archive.extractall('/data/files',filter='data'); archive.close()"
    Invoke-Docker @options run --rm --no-deps --volume "${backupDirectory}:/backup:ro" --volume "${ProjectRoot}/scripts:/tools:ro" api python /tools/backup_verify.py verify
    Invoke-Docker @options up -d --no-deps --wait api
    Invoke-Docker @options exec -T api python -c "import urllib.request; print('Restored API readiness:', urllib.request.urlopen('http://localhost:8000/api/v1/health/ready').status)"
    'Verified in isolated project ' + $project | Set-Content -LiteralPath (Join-Path $backupDirectory 'restore-verification.txt') -Encoding UTF8
} finally {
    # Only this freshly created, uniquely named drill project is removed.
    Invoke-Docker @options down --volumes
}
