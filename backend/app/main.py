"""FastAPI application entrypoint.

``uvicorn app.main:app`` (see Dockerfile CMD) imports ``app`` from this
module, so the FastAPI instance must exist at import time.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import admin, auth, devices, health

settings = get_settings()
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_app() -> FastAPI:
    app = FastAPI(title="IoT Temperature Platform API", version="0.1.0")
    origins = settings.cors_origins_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(devices.router)
    app.include_router(admin.router)
    return app


app = create_app()
