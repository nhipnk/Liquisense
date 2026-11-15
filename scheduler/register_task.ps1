$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Không tìm thấy Python. Hãy tạo .venv hoặc cài Python trước."
    }
    $python = $pythonCommand.Source
}

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$projectRoot\scripts\update.py`"" `
    -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "4:00 PM"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "LiquiSense Data Update" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Cập nhật dữ liệu thị trường SSI cho LiquiSense." `
    -Force | Out-Null

Write-Host "Đã tạo lịch cập nhật 16:00 từ thứ Hai đến thứ Sáu."
