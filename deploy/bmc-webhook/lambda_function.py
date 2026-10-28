"""BMC 웹후크 공개 입구(Lambda Function URL) + All Tomorrow 콘솔이 가져가는 확인 대기.

  POST /webhooks/bmc              BMC가 보낸다. x-signature-sha256 = HMAC-SHA256(BMC_WEBHOOK_SECRET, 원문) 16진수. 틀리면 403.
  GET  /internal/edge/bmc/pending 콘솔(Bearer PULL_TOKEN). ack 안 된 후원, 받은 순서.
  POST /internal/edge/bmc/ack     콘솔. {"ids":[...]} → 대기에서 지운다(다시 와도 안전).
이메일·결제 정보는 저장하지 않는다. 환불 이벤트는 같은 id를 대기에서 지운다.
"""
import base64
import hashlib
import hmac
import json
import os
import time

import boto3

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE"])


def resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body, ensure_ascii=False)}


def raw_body(event):
    b = event.get("body") or ""
    return base64.b64decode(b) if event.get("isBase64Encoded") else b.encode()


def authorized(event):
    want = os.environ["PULL_TOKEN"]
    got = (event.get("headers") or {}).get("authorization", "")
    return hmac.compare_digest(got, f"Bearer {want}")


def webhook(event):
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
    sid = str(data.get("id") or data.get("support_id") or "")
    if not sid:
        return resp(200, {"ok": True, "queued": False})
    if "refund" in kind:
        TABLE.delete_item(Key={"id": sid})
        return resp(200, {"ok": True, "removed": True})
    if not kind.startswith(("donation.", "coffee.", "support.")):
        return resp(200, {"ok": True, "queued": False})
    private = str(data.get("support_visibility", "1")) == "0" or bool(data.get("is_private"))
    name = str(data.get("supporter_name") or "").strip()
    TABLE.put_item(Item={
        "id": sid,
        "supporter_name": "익명" if private or not name or name == "Someone" else name[:40],
        "amount": str(data.get("amount") or data.get("total_amount_charged") or 0),
        "currency": str(data.get("currency") or "USD"),
        "note": "" if private else str(data.get("support_note") or data.get("message") or "")[:80],
        "supported_at": str(data.get("created_at") or ""),
        "received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "live": bool(ev.get("live_mode", True)),
    })
    return resp(200, {"ok": True, "queued": True})


def pending():
    items, kw = [], {}
    while True:
        r = TABLE.scan(**kw)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
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
    return resp(200, {"supports": out})


def ack(event):
    try:
        ids = [str(i) for i in json.loads(raw_body(event)).get("ids", [])][:500]
    except ValueError:
        return resp(422, {"error": "bad payload"})
    n = 0
    for i in ids:
        r = TABLE.delete_item(Key={"id": i}, ReturnValues="ALL_OLD")
        n += 1 if r.get("Attributes") else 0
    return resp(200, {"ok": True, "acked": n})


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    if method == "POST" and path == "/webhooks/bmc":
        return webhook(event)
    if path.startswith("/internal/edge/bmc/"):
        if not authorized(event):
            return resp(401, {"error": "unauthorized"})
        if method == "GET" and path == "/internal/edge/bmc/pending":
            return pending()
        if method == "POST" and path == "/internal/edge/bmc/ack":
            return ack(event)
    return resp(404, {"error": "not found"})
