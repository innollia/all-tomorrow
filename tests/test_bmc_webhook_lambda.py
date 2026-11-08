"""deploy/bmc-webhook/lambda_function.py 시험: 장부(olmuse 크레딧)가 죽어도 BMC에는 200, 못 넘긴 것은 남겼다가 다시 넘긴다."""
import hashlib
import hmac
import importlib.util
import io
import json
import pathlib
import sys
import types
import urllib.error

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET = "whsec-test"


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        it = self.items.get(Key["id"])
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item):
        self.items[Item["id"]] = dict(Item)

    def delete_item(self, Key, ReturnValues=None):
        old = self.items.pop(Key["id"], None)
        return {"Attributes": old} if old and ReturnValues else {}

    def scan(self, **_):
        return {"Items": [dict(v) for v in self.items.values()]}


class FakeLedger:
    """결제 id로 멱등인 장부. down이면 연결 실패."""

    def __init__(self):
        self.down = False
        self.credited = {}
        self.calls = 0

    def urlopen(self, req, timeout=None):
        self.calls += 1
        if self.down:
            raise urllib.error.URLError("connection refused")
        ev = json.loads(req.data)
        data = ev["data"]
        note = str(data.get("support_note") or "")
        credit = "brave-otter-lamp" in note
        if credit and "refund" not in ev["type"] and data["id"] not in self.credited:
            self.credited[data["id"]] = 1  # 같은 결제 id는 한 번만

        class R(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(json.dumps({"ok": True, "credit": credit}).encode())


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("TABLE", "bmc-webhook")
    monkeypatch.setenv("BMC_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("PULL_TOKEN", "pull-test")
    monkeypatch.setenv("STRUDEL_CREDITS_URL", "https://ledger.invalid")
    fake_boto3 = types.ModuleType("boto3")  # Lambda 런타임에만 있는 boto3 대신
    fake_boto3.resource = lambda *_: types.SimpleNamespace(Table=lambda _n: FakeTable())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    spec = importlib.util.spec_from_file_location("bmc_webhook", ROOT / "deploy" / "bmc-webhook" / "lambda_function.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.TABLE = FakeTable()
    m.LEDGER = FakeLedger()
    monkeypatch.setattr(m.urllib.request, "urlopen", m.LEDGER.urlopen)
    return m


def hook(m, payload):
    raw = json.dumps(payload).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    r = m.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/webhooks/bmc",
                          "headers": {"x-signature-sha256": sig}, "body": raw.decode()}, None)
    return r["statusCode"], json.loads(r["body"])


def donation(pid, note="", kind="donation.created"):
    return {"type": kind, "live_mode": True, "attempt": 1,
            "data": {"id": pid, "amount": 3, "currency": "USD", "supporter_name": "Kim", "support_note": note}}


def pending(m):
    r = m.lambda_handler({"requestContext": {"http": {"method": "GET"}}, "rawPath": "/internal/edge/bmc/pending",
                          "headers": {"authorization": "Bearer pull-test"}}, None)
    return json.loads(r["body"])


def test_ledger_down_still_200_and_kept_then_scheduled_retry_credits_once(mod):
    mod.LEDGER.down = True
    s, b = hook(mod, donation(1, "code brave-otter-lamp"))
    assert s == 200 and b["kept_for_retry"] is True
    p = pending(mod)
    assert p["supports"] == []  # 크레딧 구매인지 모르니 아직 후원 대기에 넣지 않는다
    assert [f["id"] for f in p["forward_failing"]] == ["donation.created:1"]
    mod.lambda_handler({"source": "aws.events"}, None)  # 아직 죽어 있다
    assert pending(mod)["forward_failing"][0]["attempts"] == 2
    mod.LEDGER.down = False
    assert mod.lambda_handler({"source": "aws.events"}, None) == {"retried": 1, "still_failing": 0}
    assert mod.lambda_handler({"source": "aws.events"}, None) == {"retried": 0, "still_failing": 0}
    assert mod.LEDGER.credited == {1: 1}
    assert pending(mod) == {"supports": [], "forward_failing": []}  # 크레딧 구매라 후원 아님


def test_plain_support_queued_after_retry_on_next_webhook(mod):
    mod.LEDGER.down = True
    assert hook(mod, donation(2, "thanks"))[0] == 200
    mod.LEDGER.down = False
    s, b = hook(mod, donation(3, "hi"))
    assert s == 200 and b["queued"] is True and b["retry"] == {"retried": 1, "still_failing": 0}
    assert sorted(x["id"] for x in pending(mod)["supports"]) == ["2", "3"]


def test_stuck_after_many_failures_is_marked_and_logged(mod, capsys):
    mod.LEDGER.down = True
    hook(mod, donation(4))
    for _ in range(mod.STUCK_AFTER):
        mod.lambda_handler({"source": "aws.events"}, None)
    f = pending(mod)["forward_failing"][0]
    assert f["stuck"] is True and f["attempts"] == mod.STUCK_AFTER + 1
    assert "ALERT bmc forward stuck" in capsys.readouterr().out


def test_refund_before_retried_payment_never_requeues(mod):
    mod.LEDGER.down = True
    hook(mod, donation(5, "thanks"))
    s, b = hook(mod, donation(5, kind="donation.refunded"))
    assert s == 200 and b["removed"] is True
    mod.LEDGER.down = False
    mod.lambda_handler({"source": "aws.events"}, None)
    assert pending(mod) == {"supports": [], "forward_failing": []}


def test_bad_signature_still_403_and_ack_ignores_internal_rows(mod):
    raw = json.dumps(donation(6)).encode()
    r = mod.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/webhooks/bmc",
                            "headers": {"x-signature-sha256": "00"}, "body": raw.decode()}, None)
    assert r["statusCode"] == 403
    mod.LEDGER.down = True
    hook(mod, donation(7))
    r = mod.lambda_handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/internal/edge/bmc/ack",
                            "headers": {"authorization": "Bearer pull-test"},
                            "body": json.dumps({"ids": ["fwd#donation.created:7"]})}, None)
    assert json.loads(r["body"])["acked"] == 0 and len(pending(mod)["forward_failing"]) == 1
