import asyncio
import sys
from unittest.mock import patch

import pytest

from all_tomorrow.async_runtime import run_async


@pytest.mark.parametrize('platform', ['win32', 'linux'])
def test_run_async_loop_selection(platform):
    async def probe():
        return asyncio.get_running_loop()

    real_run = asyncio.run
    with patch('all_tomorrow.async_runtime.sys.platform', platform), patch(
        'all_tomorrow.async_runtime.asyncio.run', wraps=real_run
    ) as runner:
        loop = run_async(probe())
    assert loop.is_closed()
    if platform == 'win32':
        assert isinstance(loop, asyncio.SelectorEventLoop)
        assert runner.call_args.kwargs == {'loop_factory': asyncio.SelectorEventLoop}
    else:
        assert runner.call_args.kwargs == {}


@pytest.mark.parametrize('dual', [False, True])
def test_windows_web_uses_selector(monkeypatch, dual):
    from all_tomorrow import web
    import uvicorn

    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(web, 'app_from_environment', lambda: object())
    monkeypatch.delenv('ALL_TOMORROW_TAILSCALE_SERVE_PORT', raising=False)
    if dual:
        monkeypatch.setenv('ALL_TOMORROW_TAILSCALE_SERVE_PORT', '15477')
    loops = []

    async def serve(self):
        loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0)

    monkeypatch.setattr(uvicorn.Server, 'serve', serve)
    monkeypatch.setattr(uvicorn, 'run', lambda *a, **kw: pytest.fail('creates its own loop'))
    web.run()
    assert len(loops) == (2 if dual else 1)
    assert all(isinstance(loop, asyncio.SelectorEventLoop) for loop in loops)
    assert all(loop is loops[0] for loop in loops)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows loop separation')
def test_worker_subprocess_uses_proactor(monkeypatch, tmp_path):
    from all_tomorrow.overseer.loop import run_worker
    from all_tomorrow import local_workers
    import json

    config = tmp_path / 'workers.json'
    config.write_text(json.dumps({'workers': {}}))
    monkeypatch.setenv('ALL_TOMORROW_WORKERS', str(config))
    seen = []

    class Adapter:
        capabilities = frozenset()

        async def is_available(self):
            return True

        async def execute(self, request):
            seen.append(asyncio.get_running_loop())
            child = await asyncio.create_subprocess_exec(
                sys.executable, '-c', 'print(42)', stdout=asyncio.subprocess.PIPE
            )
            stdout, _ = await child.communicate()
            assert child.returncode == 0 and stdout.strip() == b'42'
            raise RuntimeError('worker loop reached')

    def adapters(config):
        return {'antigravity': Adapter()}

    monkeypatch.setattr(local_workers, 'configured_adapters', adapters)
    with pytest.raises(RuntimeError, match='worker loop reached'):
        run_async(run_worker({'project_id': 'test', 'objective': 'test'}, tmp_path))
    assert len(seen) == 1
    assert isinstance(seen[0], asyncio.ProactorEventLoop)


