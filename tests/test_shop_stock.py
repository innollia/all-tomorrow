import json

from fastapi.testclient import TestClient

from all_tomorrow.web import Auth, create_app
from tests.test_shop_pay import git, shop_repo

HEAD = "// 주석\n// 상품 id: game web\n"
STOCK = {"labor": 13000, "aiHour": 5000, "aiSale": 50, "aiItems": ["game", "web"], "soldOut": [],
         "price": {"song": 2000, "research": 10000, "xpost": 1000, "dm": 5000}}


def test_save_rewrites_stock_bumps_cache_and_commits_only_two_files(tmp_path, monkeypatch) -> None:
    repo, remote = shop_repo(tmp_path)
    shop = repo / "static/shop"
    (shop / "stock.js").write_text(HEAD + "window.STOCK = " + json.dumps(STOCK, indent=2) + ";\n", encoding="utf-8")
    (shop / "index.html").write_text('<script src="stock.js?v=3"></script>\n', encoding="utf-8")
    (shop / "dialogue.js").write_text("  goods: {\n    song: { name: '노래 1곡', sub: '' },\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "stock")
    monkeypatch.setenv("ALL_TOMORROW_SHOP_REPO", str(repo))
    c = TestClient(create_app(auth=Auth("owner", "correct horse", "s" * 32), console_data_dir=str(tmp_path / "console")), base_url="https://testserver")
    c.__enter__()
    assert c.get("/api/shop-stock").status_code == 401
    c.post("/api/login", json={"username": "owner", "password": "correct horse"})
    d = c.get("/api/shop-stock").json()
    assert d["stock"] == STOCK and d["names"]["song"] == "노래 1곡" and d["names"]["dm"] == "dm"

    (repo / "other.txt").write_text("다른 세션", encoding="utf-8")
    new = {**STOCK, "labor": 15000, "aiSale": 0, "soldOut": ["song", "bot"], "price": {**STOCK["price"], "dm": 7000}}
    r = c.put("/api/shop-stock", json=new).json()
    assert r["commit"]
    text = git(repo, "show", "origin/main:static/shop/stock.js")
    assert text.startswith(HEAD)
    assert json.loads(text.split("window.STOCK = ", 1)[1].rstrip().rstrip(";")) == new
    assert "stock.js?v=4" in git(repo, "show", "origin/main:static/shop/index.html")
    assert sorted(git(repo, "show", "--name-only", "--format=", "HEAD").split()) == ["static/shop/index.html", "static/shop/stock.js"]
    assert "other.txt" in git(repo, "status", "--short")

    assert c.put("/api/shop-stock", json=new).json()["unchanged"]
    assert c.put("/api/shop-stock", json={**new, "soldOut": ["nope"]}).status_code == 422
    assert c.put("/api/shop-stock", json={**new, "aiSale": 101}).status_code == 422
    assert git(remote, "rev-list", "--count", "main").strip() == "3"
