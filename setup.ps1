param([switch]$ShortcutOnly)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
Set-Location -LiteralPath $taskRoot
try {
    if (-not $ShortcutOnly) {
        Write-Host '正在准备千鱼桌面版，请等到安装完成再关闭此窗口。'
        $taskHasPython = $false
        $taskLocalConfig = Join-Path $taskRoot '.runtime\local.json'
        if (Test-Path -LiteralPath $taskLocalConfig) {
            $taskLocalPython = (Get-Content -LiteralPath $taskLocalConfig -Raw -Encoding UTF8 | ConvertFrom-Json).python
            $taskHasPython = Test-Path -LiteralPath $taskLocalPython
        }
        foreach ($taskCandidatePath in @((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'), (Join-Path $env:ProgramFiles 'Python312\python.exe'))) {
            if (Test-Path -LiteralPath $taskCandidatePath) { $taskHasPython = $true }
        }
        if (-not $taskHasPython) {
            foreach ($taskCandidate in @('py','python')) {
                if (Get-Command $taskCandidate -ErrorAction SilentlyContinue) {
                    try {
                        $taskArgs = @('-c','import sys; assert sys.version_info[:2] == (3,12)')
                        if ($taskCandidate -eq 'py') { $taskArgs = @('-3.12') + $taskArgs }
                        & $taskCandidate @taskArgs 2>$null
                        if ($LASTEXITCODE -eq 0) { $taskHasPython = $true; break }
                    } catch { }
                }
            }
        }
        if (-not $taskHasPython) {
            Write-Host '正在获取官方 Python 安装器，请完成弹出的正常安装向导，随后会继续。'
            $taskDownloads = Join-Path $taskRoot '.tools\downloads'
            New-Item -ItemType Directory -Path $taskDownloads -Force | Out-Null
            $taskPythonInstaller = Join-Path $taskDownloads 'python-3.12.10-amd64.exe'
            Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $taskPythonInstaller
            $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskPythonInstaller
            if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Python Software Foundation') { throw 'The official Python installer signature could not be verified.' }
            Start-Process -FilePath $taskPythonInstaller -Wait
        }
        & (Join-Path $taskRoot 'install.ps1')
        if (-not (Test-Path -LiteralPath (Join-Path $taskRoot '.runtime\site-packages\webview'))) { throw 'Dependency preparation did not finish.' }
        $taskWebView = @((Join-Path ${env:ProgramFiles(x86)} 'Microsoft\EdgeWebView\Application'), (Join-Path $env:LOCALAPPDATA 'Microsoft\EdgeWebView\Application')) | Where-Object { Test-Path -LiteralPath $_ }
        if (-not $taskWebView) {
            Write-Host '正在获取微软官方桌面网页组件，请完成弹出的安装向导。'
            $taskWebInstaller = Join-Path $taskRoot '.tools\WebView2Setup.exe'
            Invoke-WebRequest 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $taskWebInstaller
            $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskWebInstaller
            if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') { throw 'The Microsoft WebView2 installer signature could not be verified.' }
            Start-Process -FilePath $taskWebInstaller -Wait
        }
    }
    $taskLauncher = Join-Path $taskRoot '千鱼.exe'
    if (-not (Test-Path -LiteralPath $taskLauncher)) {
        $taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
        & $taskCompiler /nologo /target:winexe '/reference:System.Windows.Forms.dll' ('/win32icon:' + (Join-Path $taskRoot 'fatfish\web\assets\qianyu.ico')) ('/out:' + $taskLauncher) (Join-Path $taskRoot 'scripts\Launcher.cs')
        if ($LASTEXITCODE -ne 0) { throw 'Desktop launcher build failed.' }
    }
    $taskShell = New-Object -ComObject WScript.Shell
    $taskLink = $taskShell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '千鱼.lnk'))
    # 脚本入口使用系统运行时；开发机不要求运行新编译的未签名 EXE。
    $taskLink.TargetPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $taskLink.Arguments = '-NoProfile -WindowStyle Hidden -File "' + (Join-Path $taskRoot 'launch.ps1') + '"'
    $taskLink.WorkingDirectory = $taskRoot
    $taskLink.Description = '千鱼'
    $taskLink.IconLocation = (Join-Path $taskRoot 'fatfish\web\assets\qianyu.ico') + ',0'
    $taskLink.Save()
    Write-Host '准备完成。桌面已创建“千鱼”快捷方式，首次打开会自动准备 QQ 扫码登录。'
    if (-not $ShortcutOnly) { & (Join-Path $taskRoot 'launch.ps1') }
} catch {
    Write-Host $_ -ForegroundColor Red
    Read-Host '安装尚未完成，请查看上面的提示。按回车关闭'
    exit 1
}
