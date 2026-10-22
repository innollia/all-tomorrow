"""실패한 요청만 기록한다. URL·헤더·본문·예외 메시지는 비밀값 때문에 제외한다."""
import logging

log = logging.getLogger("all_tomorrow.api")


class FailureLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = None

        async def observe(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception as error:
            log.error("request failed error=%s status=%s", type(error).__name__, status)
            raise
        else:
            if status is not None and status >= 400:
                log.warning("request failed status=%s", status)
