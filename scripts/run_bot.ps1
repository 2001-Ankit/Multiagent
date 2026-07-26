# Supervisor for the multi-agent Discord bot.
# Starts the bot and restarts it automatically if it exits or crashes.
# All bot output is appended to logs\bot.log (rotated at ~5 MB).
#
# Run manually:   powershell -ExecutionPolicy Bypass -File scripts\run_bot.ps1
# Auto-start:     powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1

$ErrorActionPreference = 'Continue'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$logDir = Join-Path $projectRoot 'logs'
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}
$botLog = Join-Path $logDir 'bot.log'
$runLog = Join-Path $logDir 'supervisor.log'

function Write-Supervisor([string]$message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$stamp] [supervisor] $message"
    Write-Output $line
    Add-Content -Path $runLog -Value $line -Encoding utf8
}

function Rotate-IfLarge([string]$path) {
    if (Test-Path $path) {
        if ((Get-Item $path).Length / 1MB -gt 5) {
            $backup = "$path.1"
            if (Test-Path $backup) { Remove-Item $backup -Force }
            Rename-Item -Path $path -NewName (Split-Path $backup -Leaf)
        }
    }
}

Write-Supervisor "started (project: $projectRoot)"

while ($true) {
    Rotate-IfLarge $botLog
    Rotate-IfLarge $runLog
    Write-Supervisor 'starting bot...'

    # cmd handles the append (>>) and stream merge (2>&1), which keeps native stderr
    # out of PowerShell's error stream and preserves logs across restarts.
    $command = "uv run python src/discord_bot.py >> `"$botLog`" 2>&1"
    try {
        $process = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $command `
            -WorkingDirectory $projectRoot -NoNewWindow -PassThru -Wait
        $code = $process.ExitCode
    } catch {
        Write-Supervisor "launcher error: $_"
        $code = -1
    }

    Write-Supervisor "bot exited (code $code); restarting in 15s"
    Start-Sleep -Seconds 15
}
