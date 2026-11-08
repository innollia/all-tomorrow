"""BMC 웹후크 공개 입구(Lambda Function URL) + All Tomorrow 콘솔이 가져가는 확인 대기.

  POST /webhooks/bmc              BMC가 보낸다. x-signature-sha256 = HMAC-SHA256(BMC_WEBHOOK_SECRET, 원문) 16진수. 틀리면 403.
  GET  /internal/edge/bmc/pending 콘솔(Bearer PULL_TOKEN). ack 안 된 후원, 받은 순서. forward_failing = 장부에 못 넘긴 것.
  POST /internal/edge/bmc/ack     콘솔. {"ids":[...]} → 대기에서 지운다(다시 와도 안전).
  EventBridge 예약 호출(source aws.events)  못 넘긴 것을 다시 넘긴다.
이메일·결제 정보는 저장하지 않는다(장부에 아직 못 넘긴 원문만 넘길 때까지 잠시 보관). 환불 이벤트는 같은 id를 대기에서 지운다.
서명이 맞는 이벤트는 모두 원문과 서명 그대로 STRUDEL_CREDITS_URL(olmuse 크레딧 장부)의 /webhooks/bmc로 넘긴다.
장부가 결제 코드(단어 코드 brave-otter-lamp, 예전 SD-XXXXXX)를 찾으면 "credit": true 로 답하고, 그런 결제는
크레딧 구매라 후원 대기·명단에 넣지 않는다(코드가 공개 명단에 나가지 않게). 코드가 없는 결제는 평소처럼 후원으로 쌓는다.

장부가 죽거나 오류여도 BMC에는 200으로 답한다(장부 때문에 블로그 결제 처리가 막히지 않게). 못 넘긴 이벤트는
같은 표에 id "fwd#..." 로 원문·서명째 남기고, 예약 호출(10분마다)과 다음 웹후크 때 다시 넘긴다. 장부는 결제 id로
멱등이라 여러 번 넘겨도 한 번만 들어간다. 넘기기 전에는 크레딧 구매인지 모르므로 그 결제의 후원 대기 저장은 넘긴 뒤에 한다.
STUCK_AFTER 번 넘게 실패하면 로그에 ALERT를 찍고 pending 응답의 forward_failing 에 보인다.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE"])
FWD = "fwd#"            # 장부에 못 넘긴 이벤트
REFUNDED = "refunded#"  # 환불된 후원 id(넘기기 전 환불이 먼저 처리돼도 나중에 대기에 다시 넣지 않게)
STUCK_AFTER = 6         # 예약 호출 10분 간격이면 약 1시간


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def forward_to_strudel(body, sig, timeout=5):
    """(넘겼는지, 크레딧 구매인지, 실패 이유)."""
    url = os.environ.get("STRUDEL_CREDITS_URL", "").rstrip("/")
    if not url:
        return True, False, ""
    req = urllib.request.Request(url + "/webhooks/bmc", data=body, method="POST",
                                 headers={"content-type": "application/json", "x-signature-sha256": sig})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                return False, False, f"http {r.status}"
            try:
                return True, bool(json.load(r).get("credit")), ""
            except ValueError:
                return True, False, ""
    except urllib.error.HTTPError as e:
        return False, False, f"http {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, False, type(e).__name__ + ": " + str(getattr(e, "reason", e))[:120]


def resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body, ensure_ascii=False)}


def raw_body(event):
    b = event.get("body") or ""
    return base64.b64decode(b) if event.get("isBase64Encoded") else b.encode()


def authorized(event):
    want = os.environ["PULL_TOKEN"]
    got = (event.get("headers") or {}).get("authorization", "")
    return hmac.compare_digest(got, f"Bearer {want}")


def support_id(data):
    return str(data.get("id") or data.get("support_id") or "")


def fwd_key(kind, data, body):
    sid = support_id(data)
    return FWD + (f"{kind}:{sid}" if sid else hashlib.sha256(body).hexdigest()[:32])


def is_support(kind):
    return kind.startswith(("donation.", "coffee.", "support."))


def queue_support(ev, data):
    """후원 대기에 쌓는다. 장부가 크레딧 구매가 아니라고 답한 뒤에만 부른다."""
    sid = support_id(data)
    if TABLE.get_item(Key={"id": REFUNDED + sid}).get("Item"):
        return False
    private = str(data.get("support_visibility", "1")) == "0" or bool(data.get("is_private"))
    name = str(data.get("supporter_name") or "").strip()
    TABLE.put_item(Item={
        "id": sid,
        "supporter_name": "익명" if private or not name or name == "Someone" else name[:40],
        "amount": str(data.get("amount") or data.get("total_amount_charged") or 0),
        "currency": str(data.get("currency") or "USD"),
        "note": "" if private else str(data.get("support_note") or data.get("message") or "")[:80],
        "supported_at": str(data.get("created_at") or ""),
        "received_at": now_iso(),
        "live": bool(ev.get("live_mode", True)),
    })
    return True


def after_forward(ev, credit):
    """장부가 받은 뒤의 블로그 쪽 일: 크레딧 구매가 아닌 후원이면 대기에 쌓는다."""
    kind, data = str(ev.get("type", "")), ev.get("data") or {}
    if not support_id(data) or "refund" in kind or not is_support(kind):
        return {"queued": False}
    if credit:  # olmuse 크레딧 구매는 후원이 아니다
        return {"queued": False, "credit": True}
    return {"queued": queue_support(ev, data)}


def remember_failed(key, body, sig, err, old=None):
    old = old or {}
    attempts = int(old.get("attempts", 0)) + 1
    item = {"id": key, "body": base64.b64encode(body).decode(), "sig": sig,
            "first_at": old.get("first_at") or now_iso(), "last_at": now_iso(),
            "attempts": attempts, "last_error": err[:200], "stuck": attempts >= STUCK_AFTER}
    TABLE.put_item(Item=item)
    if attempts >= STUCK_AFTER:
        print(json.dumps({"alert": "ALERT bmc forward stuck", "key": key, "attempts": attempts, "error": err[:200]}))
    else:
        print(json.dumps({"warn": "bmc forward failed, kept for retry", "key": key, "attempts": attempts, "error": err[:200]}))


def failed_forwards():
    items, kw = [], {}
    while True:
        r = TABLE.scan(**kw)
        items += [x for x in r["Items"] if str(x["id"]).startswith(FWD)]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return sorted(items, key=lambda x: x.get("first_at", ""))


def retry_forwards(context=None, limit=None, reserve_ms=7000):
    """못 넘긴 것을 받은 순서대로 다시 넘긴다. 성공하면 블로그 쪽 일을 마치고 지운다."""
    done = failed = 0
    for x in failed_forwards()[:limit]:
        if context is not None and context.get_remaining_time_in_millis() < reserve_ms:
            break
        body = base64.b64decode(x["body"])
        sent, credit, err = forward_to_strudel(body, x["sig"])
        if not sent:
            remember_failed(x["id"], body, x["sig"], err, x)
            failed += 1
            continue
        after_forward(json.loads(body), credit)
        TABLE.delete_item(Key={"id": x["id"]})
        done += 1
    return {"retried": done, "still_failing": failed}


def webhook(event, context=None):
    body = raw_body(event)
    sig = (event.get("headers") or {}).get("x-signature-sha256", "").strip().lower()
    want = hmac.new(os.environ["BMC_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(sig, want):
        return resp(403, {"error": "bad signature"})
    try:
        ev = json.loads(body)
    except ValueError:
        return resp(422, {"error": "bad payload"})
    kind, data = str(ev.get("type", "")), ev.get("data") or {}
    sid = support_id(data)
    if sid and "refund" in kind:  # 블로그 쪽 환불 처리는 장부와 상관없이 바로 한다
        TABLE.put_item(Item={"id": REFUNDED + sid, "received_at": now_iso()})
        TABLE.delete_item(Key={"id": sid})
    sent, credit, err = forward_to_strudel(body, sig)
    if not sent:
        # 여기서 저장까지 실패하면 이벤트를 잃으니 그때만 5xx로 BMC가 다시 보내게 한다(보통은 DynamoDB가 살아 있다)
        key = fwd_key(kind, data, body)
        remember_failed(key, body, sig, err, TABLE.get_item(Key={"id": key}).get("Item"))
        out = {"ok": True, "forwarded": False, "kept_for_retry": True, "queued": False}
        if sid and "refund" in kind:
            out["removed"] = True
        return resp(200, out)
    out = {"ok": True, "forwarded": True, **after_forward(ev, credit)}
    if sid and "refund" in kind:
        out["removed"] = True
    try:  # 장부가 살아 있으니 밀린 것도 조금 넘긴다(실패해도 이 응답과 상관없다)
        out["retry"] = retry_forwards(context, limit=3, reserve_ms=6000)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"warn": "retry on webhook failed", "error": type(e).__name__}))
    return resp(200, out)


def pending():
    items, kw = [], {}
    while True:
        r = TABLE.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    fails = sorted((x for x in items if str(x["id"]).startswith(FWD)), key=lambda x: x.get("first_at", ""))
    items = [x for x in items if not str(x["id"]).startswith((FWD, REFUNDED))]
    items.sort(key=lambda x: x.get("received_at", ""))
    out = []
    for x in items[:500]:
        try:
            amount = float(x["amount"])
            amount = int(amount) if amount.is_integer() else amount
        except (ValueError, KeyError):
            amount = 0
        out.append({"id": x["id"], "supporter_name": x.get("supporter_name", "익명"), "amount": amount,
                    "currency": x.get("currency", ""), "note": x.get("note", ""), "supported_at": x.get("supported_at", ""),
                    "received_at": x.get("received_at", ""), "live": bool(x.get("live", True))})
    failing = [{"id": x["id"][len(FWD):], "attempts": int(x.get("attempts", 0)), "first_at": x.get("first_at", ""),
                "last_at": x.get("last_at", ""), "last_error": x.get("last_error", ""), "stuck": bool(x.get("stuck"))}
               for x in fails]
    return resp(200, {"supports": out, "forward_failing": failing})


def ack(event):
    try:
        ids = [str(i) for i in json.loads(raw_body(event)).get("ids", [])][:500]
    except ValueError:
        return resp(422, {"error": "bad payload"})
    n = 0
    for i in ids:
        if i.startswith((FWD, REFUNDED)):
            continue
        r = TABLE.delete_item(Key={"id": i}, ReturnValues="ALL_OLD")
        n += 1 if r.get("Attributes") else 0
    return resp(200, {"ok": True, "acked": n})


def lambda_handler(event, context):
    if event.get("source") == "aws.events" or event.get("retry_forwards"):
        r = retry_forwards(context)
        print(json.dumps({"scheduled_retry": r}))
        return r
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    if method == "POST" and path == "/webhooks/bmc":
        return webhook(event, context)
    if path.startswith("/internal/edge/bmc/"):
        if not authorized(event):
            return resp(401, {"error": "unauthorized"})
        if method == "GET" and path == "/internal/edge/bmc/pending":
            return pending()
        if method == "POST" and path == "/internal/edge/bmc/ack":
            return ack(event)
    return resp(404, {"error": "not found"})
