[CmdletBinding()]
param([string]$EveRepo = 'C:\projects\eve-scene-runtime')
$ErrorActionPreference = 'Stop'
$EveRepo = (Resolve-Path -LiteralPath $EveRepo).Path
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
if (-not $env:ALL_TOMORROW_URL) { $env:ALL_TOMORROW_URL = 'http://127.0.0.1:5476' }
Set-Location -LiteralPath $EveRepo
# Node의 기존 .env 로더가 Discord·페르소나 설정을 읽는다. 값은 출력하지 않는다.
@'
for (const k of ['DISCORD_TOKEN', 'DISCORD_OWNER_USER_ID', 'ALL_TOMORROW_EDGE_TOKEN']) {
    if (!process.env[k]) { console.error(k + ' 설정 필요'); process.exit(1); }
}
'@ | & node --env-file=.env --input-type=module
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& node src/discord/bot-agent.mjs
exit $LASTEXITCODE
