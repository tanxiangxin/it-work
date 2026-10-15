param([string]$OutputDirectory)
. "$PSScriptRoot/docker-common.ps1"
if (!$OutputDirectory) { $OutputDirectory = Join-Path $ProjectRoot ('work/backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Backup target already exists; choose a new directory.' }
$backupDirectory = (New-Item -ItemType Directory -Path $OutputDirectory).FullName
$running = @(& docker compose ps --status running --services) | Where-Object { $_ -in @('api','worker','scheduler') }
try {
    if ($running.Count) { Invoke-Docker compose stop @running }
    Invoke-Docker compose exec -T postgres pg_dump -U campus -d campus -Fc -f /tmp/campus-backup.dump
    Invoke-Docker compose cp postgres:/tmp/campus-backup.dump "$backupDirectory/campus.dump"
    Invoke-Docker compose run --rm --no-deps --volume "${backupDirectory}:/backup" --volume "${ProjectRoot}/scripts:/tools:ro" api python /tools/backup_verify.py snapshot
    Invoke-Docker compose run --rm --no-deps --volume "${backupDirectory}:/backup" api python -c "import tarfile; archive=tarfile.open('/backup/files.tar.gz','w:gz'); archive.add('/data/files',arcname='.'); archive.close()"
    $checksums = @{}
    foreach ($name in @('campus.dump','files.tar.gz','manifest.json')) { $checksums[$name] = (Get-FileHash -LiteralPath (Join-Path $backupDirectory $name) -Algorithm SHA256).Hash }
    $checksums | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupDirectory 'checksums.json') -Encoding UTF8
    Write-Output "Backup complete: $backupDirectory"
} finally {
    if ($running.Count) { Invoke-Docker compose start @running }
}
