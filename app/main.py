from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.llm import OpenAILLM
from app.routes import router


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="ChitChat")
    app.state.settings = settings or Settings()
    app.state.llm = OpenAILLM(app.state.settings.openai_api_key)
    app.include_router(router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # Mounted last so /api and /healthz routes win.
    app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
    return app


app = create_app()
