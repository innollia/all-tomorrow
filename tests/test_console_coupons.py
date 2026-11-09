import json

from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app

# tools/coupon.py와 같은 출력: 성공은 stdout 한 줄, 실패는 "not made: <이유>"로 종료 코드 1
TOOL = '''import json, pathlib, sys
code, credits, uses = sys.argv[1].upper(), sys.argv[2], sys.argv[4]
seen = pathlib.Path("seen.json")
made = json.loads(seen.read_text()) if seen.exists() else []
if code in made:
    sys.exit("not made: exists")
if len(code) < 6:
    sys.exit("not made: code needs 6+ letters/digits")
seen.write_text(json.dumps(made + [code]))
print(f"coupon {code}: {credits} credits, {uses} use(s), LEDGER ledger")
'''


def client(tmp_path, monkeypatch, ledger="remote") -> TestClient:
    (tmp_path / "olmuse/tools").mkdir(parents=True)
    (tmp_path / "olmuse/tools/coupon.py").write_text(TOOL.replace("LEDGER", ledger), encoding="utf-8")
    monkeypatch.setenv("ALL_TOMORROW_OLMUSE_REPO", str(tmp_path / "olmuse"))
    c = TestClient(create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path / "console")), base_url="https://testserver")
    c.__enter__()
    return c


def test_runs_the_coupon_tool_and_shows_409_for_an_existing_code(tmp_path, monkeypatch) -> None:
    c = client(tmp_path, monkeypatch)
    coupon = {"code": "olmuse10k", "credits": 10000, "uses": 1}
    assert c.post("/api/coupons", json=coupon).status_code == 401
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    first = c.post("/api/coupons", json=coupon)
    assert first.status_code == 200 and first.json() == {"code": "OLMUSE10K"}
    assert c.post("/api/coupons", json=coupon).status_code == 409
    assert c.post("/api/coupons", json={"code": "short", "credits": 5}).status_code == 400
    assert c.post("/api/coupons", json={"code": "--uses", "credits": 5}).status_code == 422
    assert c.post("/api/coupons", json={"code": "a b", "credits": 5}).status_code == 422
    assert json.loads((tmp_path / "olmuse/seen.json").read_text()) == ["OLMUSE10K"]


def test_a_coupon_made_on_the_local_ledger_is_not_success(tmp_path, monkeypatch) -> None:
    c = client(tmp_path, monkeypatch, ledger="local")
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    r = c.post("/api/coupons", json={"code": "olmuse10k", "credits": 10000})
    assert r.status_code == 503 and "local" in r.json()["error"]
