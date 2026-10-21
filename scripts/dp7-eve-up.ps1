#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$EveRepo = 'C:\projects\eve-scene-runtime',
    [string]$TaskName = 'AllTomorrow-DP7-eve'
)
$ErrorActionPreference = 'Stop'
$EveRepo = (Resolve-Path -LiteralPath $EveRepo).Path
$runner = Join-Path $PSScriptRoot 'dp7-eve-run.ps1'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -RestartCount 99 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'powershell.exe') `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $runner + '" -EveRepo "' + $EveRepo + '"') `
    -WorkingDirectory $EveRepo
$triggers = @((New-ScheduledTaskTrigger -AtStartup), (New-ScheduledTaskTrigger -AtLogOn -User $user))
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host 'Eve 봇 작업을 등록·시작했습니다. 실제 DM 도착과 재부팅 복구를 확인하세요.'
