"""Syncthing 관측·제한된 재시작. 설정과 동기화 데이터는 수정하지 않는다."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from contextlib import closing
from urllib.parse import urlparse

import httpx

from . import reports
from .store import host_name, peer_paths, open_peer
from .workspace import save


def powershell(script):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', "[Console]::OutputEncoding=[Text.Encoding]::UTF8; $ErrorActionPreference='Stop'; " + script],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('powershell_failed')
    return result.stdout.strip()


def inventory():
    raw = powershell("$p=@(Get-CimInstance Win32_Process -Filter \"Name='syncthing.exe'\" | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine); $t=@(Get-NetTCPConnection -State Listen -ErrorAction Stop | Select-Object LocalPort,OwningProcess); $u=@(Get-NetUDPEndpoint -ErrorAction Stop | Select-Object LocalPort,OwningProcess); @{processes=$p; listeners=$t; udp=$u} | ConvertTo-Json -Depth 4 -Compress")
    return json.loads(raw)


def tree_count(processes):
    parents = {p['ProcessId']: p['ParentProcessId'] for p in processes}
    roots = set()
    for pid in parents:
        seen = set()
        while pid in parents and pid not in seen:
            seen.add(pid)
            parent = parents[pid]
            if parent not in parents:
                break
            pid = parent
        roots.add(pid)
    return len(roots)


def alive(host):
    try:
        # TCP works even when ICMP is disabled; Tailscale ping also detects a live peer.
        with socket.create_connection((host, 445), timeout=2):
            return True
    except OSError:
        exe = shutil.which('tailscale')
        if not exe:
            return False
        try:
            return subprocess.run([exe, 'ping', '-c', '1', '--timeout=3s', host],
                                  capture_output=True, timeout=6,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False


def inspect(config, *, get=httpx.get, snapshot=inventory, probe=alive, now=None):
    now = now or time.time()
    result = {'host': host_name(), 'at': now, 'issues': [], 'devices': []}
    try:
        root = ET.parse(config).getroot()
        gui = root.find('gui')
        if gui is None:
            raise ValueError('missing_gui')
        address = gui.findtext('address', '127.0.0.1:8384')
        if address.startswith('0.0.0.0:'):
            address = '127.0.0.1:' + address.rsplit(':', 1)[1]
        if address.startswith('[::]:'):
            address = '[::1]:' + address.rsplit(':', 1)[1]
        url = ('https' if gui.get('tls') == 'true' else 'http') + '://' + address
        headers = {'X-API-Key': gui.findtext('apikey', '')}
        def api(path):
            return get(url + '/rest/' + path, headers=headers, timeout=5)
        try:
            response = api('system/ping')
            if response.status_code in (401, 403) or 'CSRF' in response.text:
                status = 'key_rejected'
            elif response.status_code == 200 and response.json().get('ping') == 'pong':
                status = 'pong'
            else:
                status = 'other'
        except httpx.ConnectError:
            status = 'connection_refused'
        except (httpx.HTTPError, ValueError):
            status = 'other'
        result['ping'] = status
        if status != 'pong':
            result['issues'].append(status)
        try:
            data = snapshot()
            processes = data['processes'] or []
            result['processes'] = [{'pid': p['ProcessId'], 'parent': p['ParentProcessId'],
                                    'executable': p.get('ExecutablePath'),
                                    # Command lines may contain credentials. Keep only explicit home paths.
                                    'homes': re.findall(r'--(?:home|config|data)[= ]+("[^"]+"|\S+)', p.get('CommandLine') or '')}
                                   for p in processes]
            result['trees'] = tree_count(processes)
            if result['trees'] > 1:
                result['issues'].append('duplicate')
            addresses = [e.text for e in root.findall('./options/listenAddress')] or ['default']
            ports = {22000 if a == 'default' else urlparse(a).port for a in addresses if a == 'default' or a.startswith('tcp://')}
            udp_ports = {urlparse(a).port for a in addresses if a.startswith('quic://')}
            pids = {p['ProcessId'] for p in processes}
            listening = {t['LocalPort'] for t in data['listeners'] or [] if t['OwningProcess'] in pids}
            udp_listening = {t['LocalPort'] for t in data.get('udp', []) or [] if t['OwningProcess'] in pids}
            result['ports'] = sorted(p for p in ports | udp_ports if p)
            if not ports.issubset(listening) or not udp_ports.issubset(udp_listening):
                result['issues'].append('port_missing')
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            result['issues'].append('inventory_unavailable')
        if status == 'pong':
            connections = api('system/connections'); connections.raise_for_status()
            connections = connections.json().get('connections', {})
            local = api('system/status'); local.raise_for_status()
            local_id = local.json().get('myID')
            seen = api('stats/device'); seen.raise_for_status()
            stats = seen.json()
            for device in root.findall('device'):
                identity = device.get('id')
                if identity == local_id:
                    continue
                connected = connections.get(identity, {}).get('connected', False)
                last = stats.get(identity, {}).get('lastSeen')
                name = device.get('name') or identity[:7]
                hosts = [urlparse(a.text).hostname for a in device.findall('address') if a.text and a.text != 'dynamic']
                hosts.append(name)  # Tailscale MagicDNS 이름도 시도한다.
                if identity.startswith('DOC5FPZ'):
                    hosts.append('100.91.14.13')
                age = None
                if last:
                    age = now - datetime.fromisoformat(last.replace('Z', '+00:00')).timestamp()
                live = not connected and age is not None and age > 7200 and any(probe(h) for h in hosts if h)
                result['devices'].append({'id': identity, 'name': name, 'connected': connected,
                                          'lastSeen': last, 'alive_but_disconnected': live})
                if live:
                    result['issues'].append('peer_disconnected:' + identity[:7])
    except (OSError, ValueError, ET.ParseError, httpx.HTTPError, RuntimeError, subprocess.TimeoutExpired):
        result['issues'].append('inspection_failed')
    return result


def restart(config):
    # Use the existing startup shortcut and wait until all old processes have exited.
    powershell("Get-Process syncthing -ErrorAction SilentlyContinue | Stop-Process -Force; $end=(Get-Date).AddSeconds(15); while(Get-Process syncthing -ErrorAction SilentlyContinue) { if((Get-Date) -gt $end){throw 'stop_timeout'}; Start-Sleep -Milliseconds 200 }")
    startup = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Startup'
    shortcut = next((p for p in startup.glob('*.lnk') if 'syncthing' in p.name.lower()), None)
    if shortcut:
        escaped = str(shortcut).replace("'", "''")
        powershell(f"Start-Process -FilePath '{escaped}' -WindowStyle Hidden")
    else:
        exe = shutil.which('syncthing') or str(config.parent / 'syncthing.exe')
        subprocess.Popen([exe, 'serve', '--no-browser', '--no-console', '--home', str(config.parent)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def describe(cause):
    if cause.startswith('peer_disconnected:'):
        return '상대는 살아 있는데 Syncthing만 끊김: ' + cause.split(':', 1)[1]
    return {'connection_refused': '연결 거부', 'key_rejected': '키 거부(CSRF·403)',
            'other': '기타 API 오류', 'duplicate': '중복 기동', 'port_missing': '설정 포트 미수신',
            'inventory_unavailable': '프로세스·포트 조회 불가(고장 미확정)',
            'inspection_failed': '점검 실패'}.get(cause, cause)


def notify(base, result):
    day = datetime.fromtimestamp(result['at']).strftime('%Y-%m-%d')
    for cause in sorted(set(result.get('initial_issues', [])) | set(result['issues'])):
        key = hashlib.sha256((result['host'] + cause).encode()).hexdigest()[:20]
        reports.enqueue(base, f'sync-{day}-{key}',
                        f"[보고] 동기화 {result['host']} · {describe(cause)} · 관측 {datetime.fromtimestamp(result['at']).isoformat(timespec='seconds')} · 복구 {result.get('recovery', '없음')} · 현재 {', '.join(map(describe, result['issues'])) or '정상'}")


def run(base, store, *, collect_only=False, config=None, check=inspect, repair=restart, now=None, sleep=time.sleep):
    from .runtime import singleton
    base.mkdir(parents=True, exist_ok=True)
    config = config or Path(os.environ.get('LOCALAPPDATA', '')) / 'Syncthing/config.xml'
    with singleton(base / 'sync-health.lock'):
        path = base / 'sync-health.json'
        try:
            previous = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            previous = {}
        now = now or time.time()
        result = check(config, now=now)
        result['initial_issues'] = result['issues'][:]
        history = [h for h in previous.get('repairs', []) if now - h['at'] < 86400]
        today = datetime.fromtimestamp(now).date()
        daily = sum(datetime.fromtimestamp(h['at']).date() == today for h in history)
        causes = sorted(set(result['issues']) & {'key_rejected', 'connection_refused', 'duplicate', 'port_missing'})
        if causes and 'inventory_unavailable' not in result['issues']:
            recent = any(now - h['at'] < 3600 and set(h['causes']) & set(causes) for h in history)
            if recent or daily >= 3:
                result['recovery'] = '제한으로 보류'
            else:
                history.append({'at': now, 'causes': causes})
                result['repairs'] = history
                save(path, result)  # reserve the attempt before touching a process
                try:
                    repair(config)
                    for _ in range(6):
                        sleep(2)
                        after = check(config, now=now)
                        if all(c.startswith('peer_disconnected:') for c in after['issues']):
                            break
                    after['initial_issues'] = result['initial_issues']
                    result = after
                    result['recovery'] = '성공' if all(c.startswith('peer_disconnected:') for c in after['issues']) else '실패'
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    result['recovery'] = '실패'
        result['repairs'] = history
        incidents = [i for i in previous.get('incidents', []) if now - i['at'] < 7 * 86400]
        if result['initial_issues'] or result['issues']:
            incidents.append({k: result[k] for k in ('host', 'at', 'issues', 'initial_issues', 'recovery') if k in result})
        result['incidents'] = incidents[-168:]
        save(path, result)
        store.con.execute('create table if not exists sync_health (host text primary key, payload text not null)')
        store.con.execute('insert or replace into sync_health values (?,?)', (result['host'], json.dumps(result)))
        store.commit()
        store.publish(base)
        if not collect_only:
            for incident in result['incidents']:
                notify(base, incident)
            for peer in peer_paths(base):
                try:
                    with closing(open_peer(peer)) as con:
                        for (payload,) in con.execute('select payload from sync_health'):
                            peer_result = json.loads(payload)
                            for incident in peer_result.get('incidents', [peer_result]):
                                notify(base, incident)
                except (sqlite3.Error, OSError, ValueError, KeyError):
                    continue
        return result


def summary(base):
    try:
        data = json.loads((base / 'sync-health.json').read_text(encoding='utf-8'))
        devices = ', '.join(d['name'] + (' 연결' if d['connected'] else ' 끊김') for d in data['devices'])
        return f"동기화: {', '.join(map(describe, data['issues'])) or '정상'} · {devices} · 관측 {datetime.fromtimestamp(data['at']).isoformat(timespec='minutes')}"
    except (OSError, ValueError, KeyError):
        return '동기화: 아직 점검하지 않음'
