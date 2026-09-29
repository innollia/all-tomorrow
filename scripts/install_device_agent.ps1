# All Tomorrow — Windows 기기 에이전트 설치 스크립트
#
# 로그인 시 자동으로 device-agent를 실행하는 작업 스케줄러(사용자 권한, 관리자 불필요)
# 항목을 등록한다. 이미 등록된 항목이 있으면 갱신한다.
#
# 사용법 (PowerShell, 절대경로로 실행):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\path\to\install_device_agent.ps1 `
#     -ServerUrl "http://100.97.113.3:8080" `
#     -RegistrationCode "regcode_xxxxxxxx" `
#     -RepoPath "C:\Users\fixme\Desktop\all-tomorrow"
#
# RegistrationCode는 웹 "기기" 페이지에서 한 번만 발급받아 최초 설치 시에만 필요합니다
# (등록 후에는 %LOCALAPPDATA%\all-tomorrow\device_agent_state.json 에 저장된 토큰으로 계속 동작).

param(
    [Parameter(Mandatory = $true)][string]$ServerUrl,
    [Parameter(Mandatory = $false)][string]$RegistrationCode = "",
    [Parameter(Mandatory = $true)][string]$RepoPath,
    [Parameter(Mandatory = $false)][string]$TaskName = "AllTomorrowDeviceAgent",
    [Parameter(Mandatory = $false)][string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $RepoPath)) {
    throw "RepoPath가 존재하지 않습니다: $RepoPath"
}

$venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
if ($PythonExe -eq "") {
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

$workerConfig = Join-Path $RepoPath "config\workers.local.json"
if (-not (Test-Path $workerConfig)) {
    Write-Warning "워커 설정 파일이 없습니다: $workerConfig (계속 진행하되 device-agent가 실행 워커를 못 찾을 수 있습니다)"
}

$argList = @(
    "-m", "all_tomorrow.device_agent_client",
    "--server-url", $ServerUrl,
    "--worker-config", $workerConfig
)
if ($RegistrationCode -ne "") {
    $argList += @("--registration-code", $RegistrationCode)
}

$argString = ($argList | ForEach-Object { '"' + $_ + '"' }) -join " "

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $argString -WorkingDirectory $RepoPath
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "All Tomorrow device agent (로그인 시 자동 시작, Tailscale 실행기)"

Write-Output "설치 완료: 작업 스케줄러 항목 '$TaskName' 등록됨."
Write-Output "지금 바로 시작하려면: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "상태 확인: Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Output "로그 확인: 표준출력은 작업 스케줄러가 캡처하지 않으므로, 필요하면 -Argument 뒤에 콘솔 출력을 파일로 리다이렉트하는 방식으로 바꾸세요."
