$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimeConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot '.runtime\local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$env:PYTHONUTF8 = '1'
& $runtimeConfig.python (Join-Path $PSScriptRoot 'scripts\build_release.py')
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed.' }
