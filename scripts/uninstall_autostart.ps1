# Stops the bot and removes its auto-start scheduled task.
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1

$ErrorActionPreference = 'Continue'

$taskName = 'MultiAgentDiscordBot'

try {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
    Write-Output "Stopped task '$taskName'."
} catch {
    Write-Output "Task '$taskName' was not running."
}

try {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    Write-Output "Removed scheduled task '$taskName'."
} catch {
    Write-Output "Task '$taskName' was not registered."
}

Write-Output ''
Write-Output 'Note: any bot process started by the supervisor may still be running.'
Write-Output 'Check with:  Get-Process python -ErrorAction SilentlyContinue'
