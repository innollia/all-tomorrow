import hashlib
import hmac
import json
import subprocess

from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app


def git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout


def shop_repo(tmp_path):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    repo = tmp_path / "site"
    git(tmp_path, "clone", str(remote), str(repo))
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "static/shop").mkdir(parents=True)
    (repo / "static/shop/supporters_manual.json").write_text("[]\n", encoding="utf-8")
    (repo / "static/shop/supporters.json").write_text(json.dumps([{"name": "커피", "amount": 5, "currency": "USD", "note": "",
                                                                   "date": "2026-10-01", "source": "bmc"}]), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "init")
    git(repo, "push", "origin", "HEAD:main")
    return repo, remote


def client(tmp_path, monkeypatch, secret="") -> tuple[TestClient, object, object]:
    repo, remote = shop_repo(tmp_path)
    monkeypatch.setenv("ALL_TOMORROW_SHOP_REPO", str(repo))
    monkeypatch.setenv("BMC_WEBHOOK_SECRET", secret)
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret"), console_data_dir=str(tmp_path / "console"))
    c = TestClient(app, base_url="https://testserver")
    c.__enter__()
    return c, repo, remote


PAY = {"order_id": "BONG-1028-AB12", "nickname": "민수#1", "amount": 15000, "method": "bank", "public_name": "", "note": "잘 받았어요"}


def test_confirm_appends_public_row_commits_only_supporters_and_pushes_then_undo(tmp_path, monkeypatch) -> None:
    c, repo, remote = client(tmp_path, monkeypatch)
    assert c.post("/api/shop-pay", json=PAY).status_code == 401                     # 소유자만
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    (repo / "other.txt").write_text("다른 세션 작업", encoding="utf-8")              # 섞이면 안 되는 변경
    r = c.post("/api/shop-pay", json={**PAY, "dm_user_id": "1234"}).json()
    assert r["row"] == {"name": "익명", "amount": 15000, "currency": "KRW", "note": "잘 받았어요", "date": r["row"]["date"], "source": "bank"}
    pushed = json.loads(git(repo, "show", "origin/main:static/shop/supporters_manual.json"))
    assert pushed == [r["row"]] and git(remote, "log", "-1", "--format=%s", "main").strip() == "상점: 입금 확인 BONG-1028-AB12"
    assert sorted(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == ["static/shop/supporters.json", "static/shop/supporters_manual.json"]
    assert "other.txt" in git(repo, "status", "--short")
    public = json.loads((repo / "static/shop/supporters.json").read_text(encoding="utf-8"))
    assert {p["source"] for p in public} == {"bank", "bmc"}                          # 기존 BMC 줄은 유지
    assert "민수" not in json.dumps(public, ensure_ascii=False)                       # 닉네임은 공개 목록에 안 나간다
    assert c.post("/api/shop-pay", json=PAY).status_code == 409
    assert c.get("/api/shop-pay").json()["paid"][0]["dm_user_id"] == "1234"
    assert c.post("/api/shop-pay", json={**PAY, "order_id": "../x"}).status_code == 422
    assert c.post("/api/shop-pay", json={**PAY, "order_id": "고양이바다사과나무구름"}).status_code == 200

    assert c.delete("/api/shop-pay/BONG-1028-AB12").status_code == 200
    assert len(json.loads(git(repo, "show", "origin/main:static/shop/supporters_manual.json"))) == 1
    assert [p["order_id"] for p in c.get("/api/shop-pay").json()["paid"]] == ["고양이바다사과나무구름"]


def test_bmc_webhook_checks_signature_and_only_queues(tmp_path, monkeypatch) -> None:
    c, repo, _ = client(tmp_path, monkeypatch, secret="whsec")
    body = json.dumps({"type": "donation.created", "live_mode": False, "data": {"id": 77, "supporter_name": "콩", "amount": 5,
                       "currency": "USD", "support_note": "화이팅", "supporter_email": "a@b.c"}}).encode()
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    assert c.post("/internal/bmc/webhook", content=body, headers={"x-signature-sha256": "0" * 64}).status_code == 401
    assert c.post("/internal/bmc/webhook", content=body, headers={"x-signature-sha256": sig}).json() == {"ok": True, "queued": True}
    c.post("/internal/bmc/webhook", content=body, headers={"x-signature-sha256": sig})
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    pending = c.get("/api/shop-pay").json()["pending"]
    assert len(pending) == 1 and pending[0]["name"] == "콩" and "a@b.c" not in json.dumps(pending)
    assert json.loads((repo / "static/shop/supporters_manual.json").read_text(encoding="utf-8")) == []   # 자동 공개 안 함


def test_bmc_webhook_off_without_secret(tmp_path, monkeypatch) -> None:
    c, _, _ = client(tmp_path, monkeypatch)
    assert c.post("/internal/bmc/webhook", content=b"{}", headers={"x-signature-sha256": "x"}).status_code == 503


def test_dm_unlock_requests_are_polled_and_acked_by_eve(tmp_path, monkeypatch) -> None:
    c, _, _ = client(tmp_path, monkeypatch)
    edge = {"Authorization": "Bearer edge-secret"}
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    c.post("/api/shop-pay", json={**PAY, "dm_user_id": "1234"})
    assert c.get("/internal/edge/eve/access-requests").status_code == 401
    reqs = c.get("/internal/edge/eve/access-requests", headers=edge).json()["requests"]
    assert [(r["user_id"], r["action"], r["order_id"]) for r in reqs] == [("1234", "unlock", "BONG-1028-AB12")]
    ack = {"request_id": reqs[0]["request_id"], "ok": True, "state": "unlocked"}
    assert c.post("/internal/edge/eve/access-requests/ack", json=ack, headers=edge).json() == {"ok": True}
    assert c.post("/internal/edge/eve/access-requests/ack", json=ack, headers=edge).json() == {"ok": True}   # 두 번 와도 안전
    assert c.get("/internal/edge/eve/access-requests", headers=edge).json() == {"requests": []}
    assert c.post("/api/shop-pay/BONG-1028-AB12/dm/revoke").json()["action"] == "revoke"
    assert c.get("/internal/edge/eve/access-requests", headers=edge).json()["requests"][0]["action"] == "revoke"
    assert c.get("/api/shop-pay").json()["access"][0]["state"] == "unlocked"
