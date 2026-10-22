#Requires -RunAsAdministrator
# DP7에서 관제가 검토한 뒤 실행한다. 이 파일 자체는 서비스 등록을 미리 하지 않는다.
[CmdletBinding()]
param(
    [string]$Python = "$env:USERPROFILE\.all-tomorrow\dp7-runtime\Scripts\python.exe",
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [string]$TaskPrefix = 'AllTomorrow-DP7'
)
$ErrorActionPreference = 'Stop'
$Repo = (Resolve-Path -LiteralPath $Repo).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$pool = Join-Path $env:USERPROFILE '.all-tomorrow\key-pool.env'
if (Test-Path -LiteralPath $pool) {
    foreach ($line in Get-Content -LiteralPath $pool -Encoding UTF8) {
        if ($line.Trim() -match '^([^#=\s]+)\s*=(.*)$') {
            if (-not [Environment]::GetEnvironmentVariable($Matches[1], 'Process')) {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
            }
        }
    }
}
foreach ($name in @('ALL_TOMORROW_DATABASE_URL', 'ALL_TOMORROW_ADMIN_USER', 'ALL_TOMORROW_ADMIN_PASSWORD', 'ALL_TOMORROW_SESSION_SECRET')) {
    if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) { throw "$name 설정이 필요합니다. 값은 출력하지 않습니다." }
}
& $Python -c 'import all_tomorrow, psycopg, uvicorn'
if ($LASTEXITCODE -ne 0) { throw '이 PC 전용 Python 환경에 프로젝트 의존성을 설치해야 합니다.' }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$interactive = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$triggers = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn -User $user))
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
foreach ($component in @('api', 'executor', 'overseer', 'collect')) {
    # 명령줄·task XML에는 비밀값이 없다. 매 프로세스 시작 때 key-pool.env를 읽는다.
    $arguments = '-m all_tomorrow.overseer.runtime ' + $component
    $action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $Repo
    $taskTriggers = $triggers
    $taskPrincipal = $principal
    if ($component -in @('executor', 'overseer')) {
        # CLI login and the Windows sandbox runner need the logged-in user session.
        $taskPrincipal = $interactive
        # Also recover from explicit console termination (0xC000013A), which may not trigger RestartCount.
        $taskTriggers += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Minutes 1)
    }
    if ($component -eq 'collect') {
        $taskTriggers += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
            -RepetitionInterval (New-TimeSpan -Hours 1)
    }
    Register-ScheduledTask -TaskName "$TaskPrefix-$component" -Action $action -Trigger $taskTriggers `
        -Principal $taskPrincipal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName "$TaskPrefix-$component"
}
Write-Host '웹 API(127.0.0.1:5476), 작업 실행기, 메타인지, 기록 수집을 등록·시작했습니다.'
# API 자체가 멈춰도 검사할 수 있도록 별도 S4U 작업으로 분당 실행한다.
$watchAction = New-ScheduledTaskAction -Execute $Python `
    -Argument ('-m all_tomorrow.overseer.runtime api-watchdog --api-task "' + $TaskPrefix + '-api"') -WorkingDirectory $Repo
$watchTriggers = @($triggers) + (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1))
$watchSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "$TaskPrefix-api-watchdog" -Action $watchAction -Trigger $watchTriggers `
    -Principal $principal -Settings $watchSettings -Force | Out-Null
Start-ScheduledTask -TaskName "$TaskPrefix-api-watchdog"
$activityAction = New-ScheduledTaskAction -Execute $Python -Argument '-m all_tomorrow.overseer.runtime activity' -WorkingDirectory $Repo
Register-ScheduledTask -TaskName "$TaskPrefix-activity" -Action $activityAction `
    -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) -Principal $interactive -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "$TaskPrefix-activity"
Write-Host '재부팅·로그인 뒤 작업 상태와 디스코드 실제 보고를 확인하세요. 비밀값은 출력하지 않았습니다.'
