"""Infrastructure registry and bounded, read-only health observations."""
from __future__ import annotations

import asyncio
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from all_tomorrow.console import ConsoleContext

REGISTRY = Path(__file__).resolve().parents[3] / 'config' / 'infrastructure.json'

class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Host(Record):
    id: str = Field(pattern=r'^[a-z0-9-]+$')
    name: str
    kind: Literal['desktop', 'laptop', 'aws-ec2']
    location: str
    tailscale: str
    always_on: bool
    notes: str

class Health(Record):
    kind: Literal['http', 'tcp', 'windows_task', 'process', 'none']
    target: str | None = None

    @model_validator(mode='after')
    def validate_target(self):
        if self.kind != 'none' and not self.target:
            raise ValueError('probe target required')
        if self.kind == 'http':
            url = urlsplit(self.target)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('HTTP probe must be a credential-free URL')
        return self

class Service(Record):
    id: str = Field(pattern=r'^[a-z0-9-]+$')
    name: str
    host_id: str
    description: str
    project: str
    execution: Literal['scheduled_task', 'systemd', 'startup', 'manual', 'agent-stdio', 'docker', 'cron']
    ports: list[int] = Field(default_factory=list)
    scope: Literal['local', 'tailnet', 'public']
    health: Health
    placement: Literal['must_local', 'movable', 'aws']
    placement_reason: str

    @model_validator(mode='after')
    def validate_ports(self):
        if any(not 1 <= p <= 65535 for p in self.ports) or (self.health.kind == 'tcp' and not self.ports):
            raise ValueError('valid ports required')
        return self

class Registry(Record):
    hosts: list[Host]
    services: list[Service]

    @model_validator(mode='after')
    def references(self):
        ids = {h.id for h in self.hosts}
        if len(ids) != len(self.hosts) or len({s.id for s in self.services}) != len(self.services):
            raise ValueError('duplicate infrastructure id')
        if any(s.host_id not in ids for s in self.services):
            raise ValueError('unknown host_id')
        return self

def load_registry(path: Path = REGISTRY) -> Registry:
    return Registry.model_validate_json(path.read_text(encoding='utf-8'))

def windows_observation(health: Health) -> tuple[str, str]:
    # Only fixed registry strings enter PowerShell, escaped as literal strings. Never return raw output.
    target = health.target.replace("'", "''")
    if health.kind == 'windows_task':
        script = ("$ErrorActionPreference='Stop'; $t=Get-ScheduledTask -TaskName '" + target +
                  "'; $i=$t | Get-ScheduledTaskInfo; @{state=[string]$t.State; result=$i.LastTaskResult; ran=($i.LastRunTime.Year -gt 2000)} | ConvertTo-Json -Compress")
    else:
        script = ("$ErrorActionPreference='Stop'; $p=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|node|all-tomorrow).*' -and $_.CommandLine -and $_.CommandLine.Contains('" + target + "') }); @{found=($p.Count -gt 0)} | ConvertTo-Json -Compress")
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], capture_output=True, text=True, timeout=4, check=True)
        data = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 'unknown', 'Windows 조회 불가 (권한·작업 존재 여부 확인 필요)'
    if health.kind == 'process':
        return ('ok', '프로세스 패턴 확인') if data['found'] else ('failed', '일치하는 프로세스 없음')
    if data['state'] == 'Running':
        return 'ok', '예약 작업 실행 중 (기능 응답은 별도)'
    if data['state'] == 'Ready' and data['ran'] and data['result'] == 0:
        return 'ok', '예약 대기 · 최근 실행 성공 (현재 실행 중이라는 뜻 아님)'
    if not data['ran']:
        return 'unknown', '예약 작업 실행 기록 없음'
    return 'failed', '예약 작업 비활성 또는 최근 실행 실패'

async def probe(service: Service, local_host: str, client: httpx.AsyncClient) -> dict:
    health = service.health
    state, detail = 'unknown', '확인 방법 미등록 / 원격 loopback 접근 불가'
    local = service.host_id == local_host
    if health.kind == 'http':
        hostname = urlsplit(health.target).hostname
        if not local and hostname in ('localhost', '127.0.0.1', '::1'):
            detail = '원격 호스트의 loopback URL은 확인 불가'
        else:
            try:
                response = await client.get(health.target)
                state = 'ok' if 200 <= response.status_code < 300 else 'failed'
                detail = f'HTTP {response.status_code}'
            except httpx.RequestError:
                state, detail = 'failed', 'HTTP 응답 없음 (서비스·네트워크 원인 구분 불가)'
    elif local and health.kind == 'tcp':
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(health.target, service.ports[0]), 1.5)
            writer.close()
            await writer.wait_closed()
            state, detail = 'ok', f'TCP {service.ports[0]} 연결 확인 (기능 응답은 별도)'
        except (OSError, asyncio.TimeoutError):
            state, detail = 'failed', f'TCP {service.ports[0]} 연결 실패'
    elif local and health.kind in ('windows_task', 'process') and platform.system() == 'Windows':
        state, detail = await asyncio.to_thread(windows_observation, health)
    return dict(status=state, detail=detail, checked_at=datetime.now(timezone.utc).isoformat())

class Dashboard:
    def __init__(self, registry: Registry):
        self.registry = registry
        self.snapshot = None
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def get(self):
        async with self.lock:
            if self.snapshot is not None and time.monotonic() < self.expires:
                return self.snapshot
            local_host = platform.node().split('.')[0].lower()
            semaphore = asyncio.Semaphore(6)
            async with httpx.AsyncClient(timeout=1.5, follow_redirects=False, trust_env=False) as client:
                async def observe(s):
                    async with semaphore:
                        return {**s.model_dump(), **await probe(s, local_host, client)}
                services = await asyncio.gather(*(observe(s) for s in self.registry.services))
            hosts = []
            for host in self.registry.hosts:
                entries = [s for s in services if s['host_id'] == host.id]
                failed = sum(s['status'] == 'failed' for s in entries)
                unknown = sum(s['status'] == 'unknown' for s in entries)
                # A responding service never proves the entire computer healthy.
                status = 'failed' if failed else 'unknown' if unknown or not entries else 'ok'
                hosts.append({**host.model_dump(), 'status': status, 'service_count': len(entries), 'failed_count': failed, 'unknown_count': unknown})
            self.snapshot = dict(hosts=hosts, services=services, observed_from=local_host, cache_seconds=30)
            self.expires = time.monotonic() + 30
            return self.snapshot

def build_router(ctx: ConsoleContext) -> APIRouter:
    dashboard = Dashboard(load_registry())
    router = APIRouter()

    @router.get('/api/servers')
    async def servers(_: str = Depends(ctx.current_user)) -> dict:
        return await dashboard.get()

    return router
