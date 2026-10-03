"""Logging: one stream handler for the `app.*` loggers, and a request id on every line.

The id comes from the RequestId middleware (a header `X-Request-ID` on the response carries it back to the browser),
so a failure shown in the UI can be matched to the lines the server wrote for that request. Nothing a user or the
model wrote is logged: no message text, tool arguments, file names or keys; only ids, names, counts and timings.
"""
import logging
import time
import uuid
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders

request_id: ContextVar[str] = ContextVar("request_id", default="-")
logger = logging.getLogger(__name__)


class _AddRequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


def setup(level: str) -> None:
    """Idempotent: create_app() runs once per test, and each run must not add another handler."""
    root = logging.getLogger("app")
    root.setLevel(level.upper())
    if not any(getattr(h, "_chitchat", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._chitchat = True  # pyright: ignore[reportAttributeAccessIssue]
        handler.addFilter(_AddRequestId())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
        root.addHandler(handler)


class RequestId:
    """Gives each HTTP request an id, logs one line for it when it ends (API calls only: the static files and
    /healthz are not worth a line), and sends the id back in `X-Request-ID`. Plain ASGI, for the reason given on
    SecurityHeaders in main.py."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        rid = uuid.uuid4().hex[:8]
        request_id.set(rid)
        started, status = time.monotonic(), 0

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["path"].startswith("/api/"):
                ms = (time.monotonic() - started) * 1000
                logger.info("%s %s -> %s in %.0f ms", scope["method"], scope["path"], status or "no response", ms)
