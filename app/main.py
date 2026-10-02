from contextlib import closing
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import attachments, db, store
from app.config import Settings
from app.llm import OpenAILLM
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="ChitChat")
    app.state.settings = settings or Settings()
    db.init(app.state.settings.db_path)
    with closing(db.connect(app.state.settings.db_path)) as conn:  # uploads that were never sent
        abandoned = store.purge_orphans(conn, timedelta(hours=24))
    attachments.delete_files(app.state.settings.attachments_dir, abandoned)
    app.state.llm = OpenAILLM(app.state.settings)
    app.include_router(router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # Mounted last so /api and /healthz routes win.
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
    return app
