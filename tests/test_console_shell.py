from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from all_tomorrow import console
from all_tomorrow.console import ConsoleContext
from all_tomorrow.web import Auth, create_app


def client(tmp_path, **kwargs):
    app = create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path), **kwargs)
    return TestClient(app, base_url="https://testserver")


def test_console_shell_needs_login_and_keeps_old_dashboard(tmp_path) -> None:
    with client(tmp_path) as c:
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        c.post("/api/login", json={"username": "owner", "password": "correct horse"})
        shell = c.get("/").text
        assert "/static/console/console.js" in shell and "owner" in shell
        assert "요청한 일" in c.get("/requests").text
        assert "AT.pages" in c.get("/static/console/console.js").text


def test_features_mount_behind_login(tmp_path, monkeypatch) -> None:
    def build_router(ctx: ConsoleContext) -> APIRouter:
        router = APIRouter()

        @router.get("/api/demo")
        async def demo(user: str = Depends(ctx.current_user)) -> dict:
            return {"user": user, "dir": ctx.feature_dir("demo").name}
        return router

    real = console.include_features

    def fake_include(app, ctx):
        app.include_router(build_router(ctx))
        return real(app, ctx)

    monkeypatch.setattr("all_tomorrow.web.include_features", fake_include)
    with client(tmp_path) as c:
        assert c.get("/api/demo").status_code == 401
        c.post("/api/login", json={"username": "owner", "password": "correct horse"})
        assert c.get("/api/demo").json() == {"user": "owner", "dir": "demo"}
        assert (tmp_path / "demo").is_dir()


def test_collector_token_check(tmp_path) -> None:
    import pytest
    from fastapi import HTTPException

    ctx = ConsoleContext(current_user=lambda: "x", data_dir=tmp_path, collector_token="tok")
    ctx.verify_collector("Bearer tok")
    for bad in (None, "tok", "Bearer nope"):
        with pytest.raises(HTTPException):
            ctx.verify_collector(bad)
    with pytest.raises(HTTPException) as unconfigured:
        ConsoleContext(current_user=lambda: "x", data_dir=tmp_path).verify_collector("Bearer tok")
    assert unconfigured.value.status_code == 503
