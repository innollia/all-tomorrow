from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app

EDGE = {"Authorization": "Bearer edge-secret"}


def client(tmp_path) -> TestClient:
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32, edge_token="edge-secret"),
                     console_data_dir=str(tmp_path))
    c = TestClient(app, base_url="https://testserver")
    c.__enter__()
    return c


def turn(mid: str, uid: str, role: str, at: str, text: str, name: str = "") -> dict:
    return {"message_id": mid, "user_id": uid, "user_name": name, "role": role, "created_at": at, "content": text}


def test_unlocked_dm_is_stored_per_person_in_order_owner_only_and_apart_from_digest(tmp_path) -> None:
    c = client(tmp_path)
    batch = {"source": "eve", "batch_id": "b1", "turns": [
        turn("12", "100", "eve", "2026-10-28T01:00:05+00:00", "안녕, 반가워"),
        turn("11", "100", "user", "2026-10-28T01:00:00+00:00", "이브 안녕", "민수"),
        turn("21", "200", "user", "2026-10-28T02:00:00+00:00", "내 키는 api_key=sk-abcdefghijklmnopqrstuvwxyz123456", "지아"),
    ], "access": [{"user_id": "100", "user_name": "민수", "state": "unlocked", "at": "2026-10-28T00:59:00+00:00"}]}
    assert c.post("/internal/edge/eve/unlocked-dm", json=batch).status_code == 401           # 엣지 토큰 없이는 못 넣는다
    assert c.post("/internal/edge/eve/unlocked-dm", json=batch, headers=EDGE).json() == {"added": 3, "duplicates": 0, "access": 1}
    assert c.post("/internal/edge/eve/unlocked-dm", json=batch, headers=EDGE).json()["duplicates"] == 3   # 재전송 안전
    assert c.post("/internal/edge/eve/unlocked-dm", json={**batch, "source": "x"}, headers=EDGE).status_code == 422

    assert c.get("/api/eve-dm").status_code == 401                                          # 콘솔 로그인한 소유자만
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    people = {p["user_id"]: p for p in c.get("/api/eve-dm").json()}
    assert people["100"]["user_name"] == "민수" and people["100"]["turns"] == 2 and people["100"]["state"] == "unlocked"
    convo = c.get("/api/eve-dm/100").json()
    assert [t["content"] for t in convo["turns"]] == ["이브 안녕", "안녕, 반가워"]
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in c.get("/api/eve-dm/200").json()["turns"][0]["content"]

    # 회수: 기록은 남고 '회수됨'. 늦게 온 옛 해금 상태가 덮지 않는다.
    revoke = {"source": "eve", "batch_id": "b2", "access": [{"user_id": "100", "state": "revoked", "at": "2026-10-28T03:00:00+00:00"}]}
    c.post("/internal/edge/eve/unlocked-dm", json=revoke, headers=EDGE)
    c.post("/internal/edge/eve/unlocked-dm", json={**batch, "batch_id": "b3", "turns": []}, headers=EDGE)
    convo = c.get("/api/eve-dm/100").json()
    assert convo["state"] == "revoked" and len(convo["turns"]) == 2
    assert c.get("/api/eve-dm/999").status_code == 404
