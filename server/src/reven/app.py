from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI


def create_app(*, start_background_tasks: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _ = start_background_tasks
        yield

    app = FastAPI(title="Reven", lifespan=lifespan)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"service": "reven", "status": "ok"}

    return app


app = create_app()
