# Registers the bot supervisor as a Windows Scheduled Task so it starts
# automatically when you log in and keeps running in the background.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
#
# Remove it later with scripts\uninstall_autostart.ps1

$ErrorActionPreference = 'Stop'

$taskName = 'MultiAgentDiscordBot'
$projectRoot = Split-Path -Parent $PSScriptRoot
$supervisor = Join-Path $PSScriptRoot 'run_bot.ps1'

if (-not (Test-Path $supervisor)) {
    throw "Supervisor script not found at $supervisor"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$supervisor`"" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn

# ExecutionTimeLimit 0 = never time out (the default would kill it after 3 days).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Multi-agent Discord bot (chat + scheduled briefings)' `
    -Force | Out-Null

Write-Output "Registered scheduled task '$taskName' (starts at log on)."
Write-Output ''
Write-Output 'Start it now without rebooting:'
Write-Output "  Start-ScheduledTask -TaskName $taskName"
Write-Output ''
Write-Output 'Watch the log:'
Write-Output "  Get-Content `"$projectRoot\logs\bot.log`" -Wait -Tail 30"
