import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app


def ledger(seen: list) -> HTTPServer:
    made: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers["Authorization"], body))
            code = body["code"].upper()
            status, answer = (409, {"error": "exists"}) if code in made else (200, {"code": code})
            made.add(code)
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args) -> None:
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_makes_coupon_on_the_ledger_and_shows_409_for_an_existing_code(tmp_path, monkeypatch) -> None:
    seen: list = []
    server = ledger(seen)
    monkeypatch.setenv("STRUDEL_CREDITS_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("STRUDEL_CREDITS_TOKEN", "t" * 20)
    c = TestClient(create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path / "console")), base_url="https://testserver")
    c.__enter__()
    coupon = {"code": "olmuse10k", "credits": 10000, "uses": 1}
    assert c.post("/api/coupons", json=coupon).status_code == 401
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    first = c.post("/api/coupons", json=coupon)
    assert first.status_code == 200 and first.json()["code"] == "OLMUSE10K"
    again = c.post("/api/coupons", json=coupon)
    assert again.status_code == 409 and "t" * 20 not in again.text
    path, auth, body = seen[0]
    assert path == "/api/coupon_make" and auth == "Bearer " + "t" * 20
    assert body["credits"] == 10000 and body["uses"] == 1
    assert c.post("/api/coupons", json={"code": "x", "credits": 0}).status_code == 422
    server.shutdown()
