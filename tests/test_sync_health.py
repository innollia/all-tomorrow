import json
from contextlib import closing
import sqlite3
from pathlib import Path
import httpx
from all_tomorrow.overseer import sync_health as s
from all_tomorrow.overseer.store import SessionStore, open_peer

CONFIG = '''<configuration><gui><address>127.0.0.1:8384</address><apikey>secret</apikey></gui><device id="LOCAL"/><device id="DOC5FPZ-test" name="laptop"/><options><listenAddress>default</listenAddress></options></configuration>'''


def test_inspect(tmp_path):
    config = tmp_path/'config.xml'; config.write_text(CONFIG)
    processes = [{'ProcessId': 1, 'ParentProcessId': 9}, {'ProcessId': 2, 'ParentProcessId': 1}]
    snapshot = lambda: {'processes': processes, 'listeners': [{'LocalPort': 22000, 'OwningProcess': 2}]}
    def get(url, **kwargs):
        assert kwargs['headers']['X-API-Key'] == 'secret'
        payload = {'system/ping': {'ping': 'pong'}, 'system/status': {'myID': 'LOCAL'},
                   'system/connections': {'connections': {}},
                   'stats/device': {'DOC5FPZ-test': {'lastSeen': '2020-01-01T00:00:00Z'}}}
        return httpx.Response(200, json=payload[url.split('/rest/')[1]], request=httpx.Request('GET', url))
    result = s.inspect(config, get=get, snapshot=snapshot, probe=lambda h: True)
    assert result['ping'] == 'pong' and result['trees'] == 1
    assert result['issues'] == ['peer_disconnected:DOC5FPZ']
    assert 'secret' not in json.dumps(result)
    processes.append({'ProcessId': 3, 'ParentProcessId': 9})
    assert s.tree_count(processes) == 2
    denied = s.inspect(config, get=lambda *a, **k: httpx.Response(403, text='CSRF Error'), snapshot=snapshot)
    assert {'key_rejected', 'duplicate'} <= set(denied['issues'])
    def refused(*a, **k):
        raise httpx.ConnectError('refused')
    assert 'connection_refused' in s.inspect(config, get=refused, snapshot=snapshot)['issues']
    processes.clear()
    assert 'port_missing' in s.inspect(config, get=refused, snapshot=snapshot)['issues']


def test_repair_limits_and_reports(tmp_path):
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    calls = []
    def check(config, now=None):
        return {'host': 'test', 'at': now or 100000, 'issues': ['key_rejected'], 'devices': []}
    try:
        for now in (100000, 100100, 103601, 107202, 110803):
            result = s.run(base, store, check=check, repair=lambda c: calls.append(c), now=now, sleep=lambda _: None)
        assert len(calls) == 3
        assert result['recovery'] == '제한으로 보류'
        assert len(list((base/'reports').glob('*.json'))) == 1
        assert len(result['repairs']) == 3
        with closing(open_peer(store.publish(base))) as con:
            assert json.loads(con.execute('select payload from sync_health').fetchone()[0])['host'] == 'test'
    finally:
        store.close()


def test_collect_only_peer_reporting_and_success(tmp_path, monkeypatch):
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    broken = {'host': 'laptop', 'at': 100000, 'issues': ['duplicate'], 'devices': []}
    healthy = dict(broken, issues=[])
    checks = iter([broken, healthy])
    try:
        result = s.run(base, store, collect_only=True, check=lambda *a, **k: dict(next(checks)),
                       repair=lambda _: None, now=100000, sleep=lambda _: None)
        assert result['recovery'] == '성공'
        assert not (base/'reports').exists()
        peer = tmp_path/'peer.sqlite'
        with closing(sqlite3.connect(peer)) as con:
            store.con.backup(con)
        monkeypatch.setattr(s, 'peer_paths', lambda _: [peer])
        s.run(base, store, check=lambda *a, **k: dict(healthy, host='dp7'), now=104000)
        assert not list((base/'reports').glob('*.json'))  # 자동 복구로 해결된 것은 보고하지 않는다.
    finally:
        store.close()


def test_inventory_failure_does_not_restart(tmp_path):
    config = tmp_path/'config.xml'; config.write_text(CONFIG)
    def unavailable():
        raise RuntimeError('access denied')
    result = s.inspect(config, get=lambda *a, **k: httpx.Response(403, text='CSRF'), snapshot=unavailable)
    assert result['issues'] == ['key_rejected', 'inventory_unavailable']
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    try:
        s.run(base, store, check=lambda *a, **k: dict(result), repair=lambda _: (_ for _ in ()).throw(AssertionError('must not restart')))
    finally:
        store.close()


def test_recovery_changed_failure_and_persisted_incident(tmp_path):
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    initial = {'host': 'laptop', 'at': 100000, 'issues': ['connection_refused'], 'devices': []}
    other = dict(initial, issues=['other'])
    count = [0]
    def check(*a, **k):
        count[0] += 1
        return dict(initial if count[0] == 1 else other)
    try:
        result = s.run(base, store, collect_only=True, check=check, repair=lambda _: None, now=100000, sleep=lambda _: None)
        assert result['recovery'] == '실패'
        s.run(base, store, collect_only=True, check=lambda *a, **k: dict(initial, issues=[]), now=104000)
        payload = json.loads(store.con.execute('select payload from sync_health').fetchone()[0])
        assert payload['incidents'][0]['recovery'] == '실패'
        assert payload['incidents'][0]['initial_issues'] == ['connection_refused']
    finally:
        store.close()


def test_run_cli_checks_before_collect(tmp_path, monkeypatch):
    from all_tomorrow.overseer import __main__ as cli
    order = []
    monkeypatch.setattr(s, 'run', lambda *a, **k: order.append(('health', k['collect_only'])))
    monkeypatch.setattr(cli, 'collect', lambda *a, **k: order.append(('collect', True)))
    assert cli.main(['--dir', str(tmp_path), 'run', '--collect-only']) == 0
    assert order == [('health', True), ('collect', True)]


def test_one_report_per_lasting_anomaly(tmp_path):
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    state = {'issues': ['peer_disconnected:DOC5FPZ']}
    check = lambda config, now=None: {'host': 'dp7', 'at': now, 'issues': list(state['issues']), 'devices': []}
    reports = lambda: sorted(p.name for p in (base/'reports').glob('*.json'))
    try:
        for hour in range(12):  # 반나절 안에 풀리는 끊김은 기록만 한다.
            s.run(base, store, check=check, now=100000 + hour*3600)
        assert reports() == []
        for hour in range(12, 48):  # 날짜가 바뀌어도 같은 이상은 한 번만 보고한다.
            s.run(base, store, check=check, now=100000 + hour*3600)
        assert len(reports()) == 1
        assert '사람이 확인' in json.loads((base/'reports'/reports()[0]).read_text(encoding='utf-8'))['content']
        state['issues'] = []
        s.run(base, store, check=check, now=100000 + 48*3600)
        assert json.loads((base/'sync-health.json').read_text(encoding='utf-8'))['alerts'] == {}
        state['issues'] = ['peer_disconnected:DOC5FPZ']
        for hour in range(49, 49 + 13):  # 정상으로 돌아왔다가 다시 생기면 새 이상이다.
            s.run(base, store, check=check, now=100000 + hour*3600)
        assert len(reports()) == 2
    finally:
        store.close()


def test_failed_repair_is_reported_once_and_offline_peer_is_not(tmp_path, monkeypatch):
    base = tmp_path/'overseer'; store = SessionStore(base/'overseer.sqlite')
    peer = tmp_path/'peer.sqlite'
    with closing(sqlite3.connect(peer)) as con:
        con.execute('create table sync_health (host text primary key, payload text not null)')
        con.execute('insert into sync_health values (?,?)', ('laptop', json.dumps(
            {'host': 'laptop', 'at': 100000, 'issues': ['inspection_failed'], 'devices': []})))
        con.commit()
    monkeypatch.setattr(s, 'peer_paths', lambda _: [peer])
    check = lambda config, now=None: {'host': 'dp7', 'at': now, 'issues': ['port_missing'], 'devices': []}
    try:
        for hour in range(30):  # 상대 기록은 꺼진 뒤 그대로 남아 있어도 보고하지 않는다.
            s.run(base, store, check=check, repair=lambda _: None, now=100000 + 4*3600 + hour*3600, sleep=lambda _: None)
        contents = [json.loads(p.read_text(encoding='utf-8'))['content'] for p in (base/'reports').glob('*.json')]
        assert len(contents) == 1 and '설정 포트 미수신' in contents[0] and '실패' in contents[0]
    finally:
        store.close()
