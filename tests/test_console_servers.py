import asyncio
import json
import subprocess
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from all_tomorrow.console import servers
from all_tomorrow.web import Auth, create_app


def registry():
    return servers.load_registry()


def test_registry_initial_inventory():
    r = registry()
    assert len(r.hosts) == 4 and len(r.services) == 21
    # Both former movable candidates were moved to AWS on 2026-10-24.
    assert {s.id for s in r.services if s.placement == 'aws'} >= {'litellm', 'study-post'}


@pytest.mark.parametrize('change', ['duplicate_host', 'duplicate_service', 'dangling', 'port', 'url', 'target', 'extra'])
def test_registry_rejects_invalid_data(change, tmp_path):
    d = registry().model_dump()
    if change == 'duplicate_host': d['hosts'].append(d['hosts'][0])
    if change == 'duplicate_service': d['services'].append(d['services'][0])
    if change == 'dangling': d['services'][0]['host_id'] = 'missing'
    if change == 'port': d['services'][0]['ports'] = [70000]
    if change == 'url': d['services'][0]['health']['target'] = 'http://user:password@localhost/'
    if change == 'target': d['services'][0]['health']['target'] = None
    if change == 'extra': d['hosts'][0]['secret'] = 'invalid'
    p = tmp_path / 'registry.json'
    p.write_text(json.dumps(d), encoding='utf-8')
    with pytest.raises(ValidationError): servers.load_registry(p)


@pytest.mark.parametrize('code,expected', [(200,'ok'), (503,'failed'), (302,'failed')])
async def test_http_probe(code, expected):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(code))) as c:
        r = await servers.probe(registry().services[0], 'dp7', c)
    assert r['status'] == expected and r['checked_at']


async def test_network_failure_and_remote_loopback():
    def fail(request): raise httpx.ConnectError('no connection')
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as c:
        assert (await servers.probe(registry().services[0], 'dp7', c))['status'] == 'failed'
        assert (await servers.probe(registry().services[0], 'aaaa', c))['status'] == 'unknown'
        assert (await servers.probe(registry().services[-1], 'dp7', c))['status'] == 'unknown'


async def test_tcp_success_failure(monkeypatch):
    s = next(s for s in registry().services if s.id == 'postgres')
    async def opened(*args):
        class Writer:
            def close(self): pass
            async def wait_closed(self): pass
        return None, Writer()
    monkeypatch.setattr(asyncio, 'open_connection', opened)
    async with httpx.AsyncClient() as c:
        assert (await servers.probe(s, 'dp7', c))['status'] == 'ok'
        async def fail(*args): raise OSError('refused')
        monkeypatch.setattr(asyncio, 'open_connection', fail)
        assert (await servers.probe(s, 'dp7', c))['status'] == 'failed'
        assert (await servers.probe(s, 'aaaa', c))['status'] == 'unknown'


@pytest.mark.parametrize('data,status', [({'state':'Running'},'ok'), ({'state':'Ready','ran':True,'result':0},'ok'), ({'state':'Disabled','ran':True,'result':0},'failed'), ({'state':'Ready','ran':False,'result':0},'unknown'), ({'found':False},'failed'), ({'found':True},'ok')])
def test_windows_verdict(monkeypatch, data, status):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: Mock(stdout=json.dumps(data)))
    health = servers.Health(kind='process' if 'found' in data else 'windows_task', target='test')
    assert servers.windows_observation(health)[0] == status


def test_windows_query_denied(monkeypatch):
    def fail(*a, **k): raise subprocess.CalledProcessError(1, 'powershell')
    monkeypatch.setattr(subprocess, 'run', fail)
    assert servers.windows_observation(servers.Health(kind='windows_task',target='test'))[0] == 'unknown'


async def test_cache_coalesces_and_expires(monkeypatch):
    count = 0
    now = [100.0]
    monkeypatch.setattr(servers.time, 'monotonic', lambda: now[0])
    async def fake_probe(*args):
        nonlocal count
        count += 1
        return dict(status='unknown', detail='test', checked_at='2026-10-24T00:00:00Z')
    monkeypatch.setattr(servers, 'probe', fake_probe)
    d = servers.Dashboard(registry())
    a,b = await asyncio.gather(d.get(),d.get())
    assert a is b and count == 21
    assert all(h['status'] == 'unknown' for h in a['hosts'])
    now[0] = 131
    await d.get()
    assert count == 42


def test_route_protected_and_shell_mount(tmp_path, monkeypatch):
    async def snapshot(self): return {'hosts':[], 'services':[]}
    monkeypatch.setattr(servers.Dashboard, 'get', snapshot)
    app = create_app(auth=Auth('owner','correct horse','s'*32),console_data_dir=str(tmp_path))
    with TestClient(app,base_url='https://testserver') as c:
        assert c.get('/api/servers').status_code == 401
        assert c.get('/',follow_redirects=False).status_code == 303
        c.post('/api/login',json={'username':'owner','password':'correct horse'})
        assert c.get('/api/servers').json() == {'hosts':[], 'services':[]}
        assert '/static/console/pages/servers.js' in c.get('/').text
