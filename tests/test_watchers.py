"""Stage 3.2B — webhook + watcher verification (S3-32B-01..04)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

import pytest

from all_tomorrow.domain.ids import utc_now
from all_tomorrow.watchers import (
    ConditionWatcher,
    WatchMode,
    WebhookError,
    WebhookReceiver,
)

SECRET = "whsec"


def _sig(body: bytes) -> str:
    return hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


# S3-32B-01: replayed webhook (same nonce) is a duplicate, not accepted twice.
def test_32b_01_replay_duplicate() -> None:
    r = WebhookReceiver(secret=SECRET)
    body = b'{"x":1}'
    now = utc_now()
    assert r.verify_and_accept(body=body, signature=_sig(body), nonce="n1", timestamp=now, now=now)
    assert not r.verify_and_accept(body=body, signature=_sig(body), nonce="n1", timestamp=now, now=now)


# S3-32B-02: bad signature rejected.
def test_32b_02_bad_signature_rejected() -> None:
    r = WebhookReceiver(secret=SECRET)
    body = b'{"x":1}'
    with pytest.raises(WebhookError):
        r.verify_and_accept(body=body, signature="deadbeef", nonce="n", timestamp=utc_now())


def test_32b_size_and_type_limits() -> None:
    r = WebhookReceiver(secret=SECRET, max_body_bytes=4)
    big = b"12345"
    with pytest.raises(WebhookError):
        r.verify_and_accept(body=big, signature=_sig(big), nonce="n", timestamp=utc_now())
    small = b"12"
    with pytest.raises(WebhookError):
        r.verify_and_accept(body=small, signature=_sig(small), nonce="n", timestamp=utc_now(),
                            content_type="text/xml")


def test_32b_timestamp_replay_window() -> None:
    r = WebhookReceiver(secret=SECRET, replay_window=timedelta(minutes=1))
    body = b"{}"
    old = utc_now() - timedelta(minutes=10)
    with pytest.raises(WebhookError):
        r.verify_and_accept(body=body, signature=_sig(body), nonce="n", timestamp=old)


# S3-32B-03: watcher cursor persists across observations.
def test_32b_03_watcher_cursor() -> None:
    w = ConditionWatcher(mode=WatchMode.EDGE)
    w.observe(condition=False, cursor="c1")
    assert w.cursor == "c1"
    w.observe(condition=True, cursor="c2")
    assert w.cursor == "c2"


# S3-32B-04: edge fires once on transition (no storm); poll failure ≠ false.
def test_32b_04_edge_no_storm_and_poll_failure() -> None:
    w = ConditionWatcher(mode=WatchMode.EDGE)
    assert w.observe(condition=True, cursor="c1") is True     # false->true fires
    assert w.observe(condition=True, cursor="c2") is False    # still true, no re-fire
    # poll failure is UNKNOWN, not false; does not flip state or fire
    assert w.observe(condition=None, cursor="c3") is False
    assert w.cursor == "c2"                                   # cursor unchanged on failure
    # level mode fires each true
    lw = ConditionWatcher(mode=WatchMode.LEVEL)
    assert lw.observe(condition=True, cursor="a") is True
    assert lw.observe(condition=True, cursor="b") is True
