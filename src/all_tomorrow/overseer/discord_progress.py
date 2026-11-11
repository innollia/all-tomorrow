"""Forward a project-trigger Claude run's narration to its Discord thread while it works.

Reads Claude's stream-json lines. An assistant text is posted only once a tool use follows it, so the
final answer (which the worker sends itself through the project's Discord tool) is never posted twice.
At most one post per `interval` seconds; texts in between are dropped, not queued.
"""
import json
import threading
import time
import urllib.request

from all_tomorrow.adapters.workers import KEY_POOL

API = "https://discord.com/api/v10"
LIMIT = 1900


def bot_token(key_pool=None):
    # Same source as the projects' tools/discord.py. Never printed or written anywhere.
    for line in (key_pool or KEY_POOL).read_text(encoding="utf-8-sig").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "EVE_DISCORD_BOT_TOKEN" and value.strip():
            return value.strip().strip("'\"")
    return None


def post_message(channel_id, text):
    token = bot_token()
    if not token:
        return
    request = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages", method="POST",
        data=json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode("utf-8"),
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "DiscordBot (all-tomorrow, 1)"})
    try:
        urllib.request.urlopen(request, timeout=15).close()
    except Exception:
        pass   # progress is best effort; the error may carry request details, so it is not logged


def _background(channel_id, text):
    threading.Thread(target=post_message, args=(channel_id, text), daemon=True).start()


class DiscordProgress:
    def __init__(self, channel_id, *, post=_background, clock=time.monotonic, interval=3.0):
        self.channel_id, self.post, self.clock, self.interval = channel_id, post, clock, interval
        self.pending = None
        self.last = None

    def feed(self, line):
        try:
            event = json.loads(line)
        except ValueError:
            return
        if not isinstance(event, dict):
            return
        if event.get("type") == "result":
            self.pending = None   # the last text is the final answer
            return
        if event.get("type") != "assistant":
            return
        blocks = (event.get("message") or {}).get("content") or []
        for block in blocks if isinstance(blocks, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and (block.get("text") or "").strip():
                self.pending = block["text"].strip()
            elif block.get("type") == "tool_use" and self.pending:
                self.flush()

    def flush(self):
        text, self.pending = self.pending, None
        now = self.clock()
        if self.last is not None and now - self.last < self.interval:
            return
        self.last = now
        self.post(self.channel_id, text[:LIMIT])
