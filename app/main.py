from contextlib import closing
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders

from app import attachments, db, logs, store, tools
from app.config import Settings
from app.llm import OpenAILLM
from app.routes import router

# What the browser may do with the app's pages, as defence in depth against model output or an uploaded file that
# ever slips past the sanitizer: scripts only from this origin (the app has no inline scripts, and none can be
# injected), no plugins, no framing, no <base>, requests only to this origin. Styles allow inline because KaTeX
# writes style attributes; images allow data: (the favicon) and blob: (attachment previews). The attachment
# route sets a stricter policy of its own, which is kept.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeaders:
    """Adds SECURITY_HEADERS to every HTTP response unless the route already set that header. Plain ASGI rather than
    BaseHTTPMiddleware, which wraps streaming responses in a way that gets in the way of a dropped connection
    cancelling the reply (Stop)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="ChitChat")
    app.add_middleware(SecurityHeaders)
    app.add_middleware(logs.RequestId)
    app.state.settings = settings or Settings()
    logs.setup(app.state.settings.log_level)
    db.init(app.state.settings.db_path)
    with closing(db.connect(app.state.settings.db_path)) as conn:  # uploads that were never sent
        abandoned = store.purge_orphans(conn, timedelta(hours=24))
    attachments.delete_files(app.state.settings.attachments_dir, abandoned)
    app.state.llm = OpenAILLM(app.state.settings)
    app.state.tools = tools.build(app.state.settings)
    app.include_router(router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # Mounted last so /api and /healthz routes win.
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app
