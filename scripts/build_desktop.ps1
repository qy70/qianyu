param([string]$CertificateThumbprint, [switch]$RequireSignature)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskPython = (Get-Content -LiteralPath (Join-Path $taskRoot '.runtime\local.json') -Raw -Encoding UTF8 | ConvertFrom-Json).python
$taskArguments = @((Join-Path $PSScriptRoot 'build_desktop.py'))
if ($CertificateThumbprint) { $taskArguments += @('--certificate-thumbprint', $CertificateThumbprint) }
if ($RequireSignature) { $taskArguments += '--require-signature' }
& $taskPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Native installer build failed.' }