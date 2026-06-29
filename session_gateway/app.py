"""FastAPI app do Session Gateway."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import config
from .routes import discovered, lanes, prompt, sessions, watch
from .session_manager import MANAGER


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    yield
    await MANAGER.stop_all()


app = FastAPI(title="Session Gateway", version="0.1.0", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(prompt.router)
app.include_router(discovered.router)
app.include_router(watch.router)
app.include_router(lanes.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "sessions": len(MANAGER.list()),
            "allow_dangerous_modes": config.ALLOW_DANGEROUS_MODES}


@app.exception_handler(Exception)
async def unhandled(request, exc):  # noqa: ANN001
    return JSONResponse(status_code=500,
                        content={"error": {"type": type(exc).__name__,
                                            "message": str(exc)}})
