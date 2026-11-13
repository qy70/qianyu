$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = $null
$localRuntime = Join-Path $taskRoot '.runtime\local.json'
if (Test-Path -LiteralPath $localRuntime) {
    $runtimeConfig = Get-Content -LiteralPath $localRuntime -Raw -Encoding UTF8 | ConvertFrom-Json
    if (Test-Path -LiteralPath $runtimeConfig.python) { $taskPython = $runtimeConfig.python }
}
if (-not $taskPython) {
    foreach ($candidatePath in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), (Join-Path $env:ProgramFiles 'Python312\python.exe'))) {
        if (Test-Path -LiteralPath $candidatePath) {
            & $candidatePath -c 'import sys; assert sys.version_info[:2] == (3,12)' 2>$null
            if ($LASTEXITCODE -eq 0) { $taskPython = $candidatePath; break }
        }
    }
}
if (-not $taskPython) {
    foreach ($candidate in @('py','python')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            try {
                $candidateArgs = @('-c','import sys; assert sys.version_info[:2] == (3,12); print(sys.executable)')
                if ($candidate -eq 'py') { $candidateArgs = @('-3.12') + $candidateArgs }
                $candidatePath = & $candidate @candidateArgs 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $candidatePath)) { $taskPython = $candidatePath; break }
            } catch { }
        }
    }
}
if (-not $taskPython) { throw 'Install official Python 3.12 x64 first: https://www.python.org/downloads/windows/' }
$uvExe = Join-Path $taskRoot '.tools\uv\uv.exe'
if (-not (Test-Path -LiteralPath $uvExe)) {
    New-Item -ItemType Directory -Path (Join-Path $taskRoot '.tools') -Force | Out-Null
    Invoke-WebRequest -Uri 'https://github.com/astral-sh/uv/releases/download/0.13.7/uv-x86_64-pc-windows-msvc.zip' -OutFile (Join-Path $taskRoot '.tools\uv.zip')
    Expand-Archive -LiteralPath (Join-Path $taskRoot '.tools\uv.zip') -DestinationPath (Join-Path $taskRoot '.tools\uv') -Force
}
$env:UV_CACHE_DIR = Join-Path $taskRoot '.tools\uv-cache'
& $uvExe pip install --python $taskPython --target (Join-Path $taskRoot '.runtime\site-packages') -r (Join-Path $taskRoot 'requirements-windows.lock') --index-url https://pypi.org/simple
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. See the error above.' }
@{python=$taskPython} | ConvertTo-Json | Set-Content -LiteralPath $localRuntime -Encoding UTF8
Write-Output 'Ready. Double-click the launcher to open Fatfish.'
