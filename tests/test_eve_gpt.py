import threading
import time

from fastapi.testclient import TestClient

from all_tomorrow.console import eve_gpt
from all_tomorrow.web import Auth, create_app

EDGE = {"Authorization": "Bearer edge-secret"}


def test_psych_analysis_runs_once_per_request_and_reports_status(tmp_path, monkeypatch) -> None:
    calls, gate = [], threading.Event()

    def fake(prompt, workdir):
        calls.append(prompt)
        gate.wait(5)
        return "" if "빈" in prompt else "리포트: " + prompt[:5]
    monkeypatch.setattr(eve_gpt, "codex_write", fake)
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret"), console_data_dir=str(tmp_path))
    c = TestClient(app, base_url="https://testserver")
    c.__enter__()
    body = {"request_id": "r1", "kind": "psych", "prompt": "검사 원문과 답변"}
    assert c.post("/internal/edge/eve/gpt-analysis", json=body).status_code == 401
    assert c.post("/internal/edge/eve/gpt-analysis", json=body, headers=EDGE).json() == {"accepted": True}
    assert c.post("/internal/edge/eve/gpt-analysis", json=body, headers=EDGE).json() == {"accepted": True}
    assert c.get("/internal/edge/eve/gpt-analysis/r1", headers=EDGE).json()["status"] in ("queued", "running")
    gate.set()
    for _ in range(50):
        r = c.get("/internal/edge/eve/gpt-analysis/r1", headers=EDGE).json()
        if r["status"] == "done":
            break
        time.sleep(0.05)
    assert r == {"status": "done", "result": "리포트: 검사 원문", "error": ""} and len(calls) == 1
    c.post("/internal/edge/eve/gpt-analysis", json={**body, "request_id": "r2", "prompt": "빈 결과"}, headers=EDGE)
    for _ in range(50):
        r = c.get("/internal/edge/eve/gpt-analysis/r2", headers=EDGE).json()
        if r["status"] == "failed":
            break
        time.sleep(0.05)
    assert r["status"] == "failed" and r["error"]
    assert c.get("/internal/edge/eve/gpt-analysis/zz", headers=EDGE).status_code == 404
    assert c.post("/internal/edge/eve/gpt-analysis", json={**body, "kind": "x"}, headers=EDGE).status_code == 422
