param([string]$Instance = 'my-fish', [switch]$NoOpen, [switch]$NoQQ)
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
    foreach ($candidate in @('py', 'python')) {
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
if (-not $taskPython) { throw 'Python 3.12 is required. Install the official Python 3.12 x64 distribution, then run install.ps1.' }
$env:PYTHONPATH = (Join-Path $taskRoot '.runtime\site-packages') + ';' + (Join-Path $taskRoot 'engine\MaiBot') + ';' + $taskRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONUNBUFFERED = '1'
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot '.runtime\site-packages\tomlkit'))) { throw 'Dependencies are missing. Run install.ps1 first.' }
$logRoot = Join-Path $taskRoot '.runtime'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$taskArgs = @('-m','fatfish.desktop','--instance',$Instance)
if ($NoQQ) { $taskArgs += '--no-qq' }
if ($NoOpen) { $taskArgs = @('-m','fatfish.server','--instance',$Instance,'--no-open') }
$taskWindowStyle = 'Hidden'
if (-not $NoOpen) {
    $taskPythonWindowed = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $taskPythonWindowed)) { throw 'The Python windowed runtime is missing. Repair the Python installation.' }
    $taskPython = $taskPythonWindowed
    $taskWindowStyle = 'Normal'
}
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArgs -WorkingDirectory $taskRoot -WindowStyle $taskWindowStyle -PassThru -RedirectStandardOutput (Join-Path $logRoot 'manager.out.log') -RedirectStandardError (Join-Path $logRoot 'manager.err.log')
$taskProcess.Id | Set-Content -LiteralPath (Join-Path $logRoot 'manager.pid') -Encoding ASCII
Write-Output ('Fatfish manager starting (PID ' + $taskProcess.Id + ').')
