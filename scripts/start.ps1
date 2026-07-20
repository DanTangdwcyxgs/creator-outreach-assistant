param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Logs = Join-Path $Root "logs"
$Lms = "C:\Users\Administrator\.lmstudio\bin\lms.exe"
$ModelYaml = "C:\Users\Administrator\.lmstudio\hub\models\google\gemma-4-12b\model.yaml"
$Chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$AppUrl = "http://127.0.0.1:8765/"
$ChromeProfile = Join-Path $Root "data\chrome-app-profile"

trap {
    $ErrorText = $_ | Out-String
    $ErrorText | Set-Content -LiteralPath (Join-Path $Logs "launcher-error.log") -Encoding UTF8
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "Creator Hub failed to start. Please send logs/launcher-error.log to Codex.",
        "Creator Hub"
    ) | Out-Null
    exit 1
}

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

if (-not (Test-Path -LiteralPath $Lms)) {
    throw "LM Studio CLI was not found: $Lms"
}

# LM Studio updates can restore Gemma's slow thinking mode. Keep this app's model fast.
$ReloadModel = $false
if (Test-Path -LiteralPath $ModelYaml) {
    $Yaml = Get-Content -LiteralPath $ModelYaml -Raw -Encoding UTF8
    if ($Yaml -match "defaultValue:\s*true") {
        $Yaml = $Yaml -replace "defaultValue:\s*true", "defaultValue: false"
        Set-Content -LiteralPath $ModelYaml -Value $Yaml -Encoding UTF8
        $ReloadModel = $true
    }
}

function Test-Http([string]$Url) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        return $false
    }
}

if (-not (Test-Http "http://127.0.0.1:1234/v1/models")) {
    Start-Process -FilePath $Lms -ArgumentList @("server", "start", "--port", "1234", "--bind", "127.0.0.1") -WindowStyle Hidden
    for ($i = 0; $i -lt 20 -and -not (Test-Http "http://127.0.0.1:1234/v1/models"); $i++) {
        Start-Sleep -Milliseconds 500
    }
}

$Loaded = (& $Lms ps | Out-String)
if ($ReloadModel -and $Loaded -match "gemma-4-12b") {
    & $Lms unload gemma-4-12b | Out-Null
    $Loaded = ""
}
if ($Loaded -notmatch "gemma-4-12b") {
    & $Lms load google/gemma-4-12b --context-length 8192 --gpu 0.8 --identifier gemma-4-12b --yes | Out-Null
}

if (-not (Test-Http "${AppUrl}api/health")) {
    Start-Process -FilePath "python" `
        -ArgumentList @((Join-Path $Root "server.py")) `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $Logs "app-output.log") `
        -RedirectStandardError (Join-Path $Logs "app-error.log")
    for ($i = 0; $i -lt 30 -and -not (Test-Http "${AppUrl}api/health"); $i++) {
        Start-Sleep -Milliseconds 300
    }
}

if (-not (Test-Http "${AppUrl}api/health")) {
    throw "Creator Hub failed to start. Check the logs folder."
}

if (-not $NoBrowser) {
    if (Test-Path -LiteralPath $Chrome) {
        New-Item -ItemType Directory -Force -Path $ChromeProfile | Out-Null
        Start-Process -FilePath $Chrome -ArgumentList @(
            "--user-data-dir=$ChromeProfile",
            "--app=$AppUrl",
            "--start-maximized",
            "--no-first-run",
            "--no-default-browser-check"
        )
    } else {
        Start-Process $AppUrl
    }
}
