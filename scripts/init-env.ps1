$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root '.env'
if (Test-Path -LiteralPath $target) { Write-Output '.env exists; preserved.'; exit 0 }
function New-LocalPassword {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+','-').Replace('/','_')
}
$content = [IO.File]::ReadAllText((Join-Path $root '.env.example'))
$content = $content.Replace('replace-with-a-random-db-password',(New-LocalPassword)).Replace('replace-with-a-student-password',(New-LocalPassword)).Replace('replace-with-an-admin-password',(New-LocalPassword))
# CreateNew makes concurrent initialization safe and never replaces an existing file.
$stream = [IO.File]::Open($target,[IO.FileMode]::CreateNew)
try { $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($content); $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
Write-Output 'Created .env with random passwords in Mock mode. Read passwords locally; do not commit this file.'
