"""Application factory. `app.main:app` is the ASGI entry point for uvicorn."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401  (complete metadata and model hooks before any mapper is used)
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import register_exception_handlers
from app.core.features import discover_features
from app.modules.auth.service import sync_permissions


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    with application.state.session_factory() as session:
        sync_permissions(session, application.state.permissions)
        session.commit()
    yield
    application.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    application = FastAPI(
        title="ERP",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=_lifespan,
    )
    application.state.settings = settings
    application.state.engine = make_engine(settings.database_url)
    application.state.session_factory = make_session_factory(application.state.engine)

    register_exception_handlers(application)
    if settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Content-Disposition"],
        )

    discovery = discover_features(settings.feature_list)
    application.state.features = discovery.features
    application.state.permissions = discovery.permissions
    for router in discovery.routers:
        application.include_router(router)

    @application.get("/api/health", tags=["health"])
    def health(request: Request) -> JSONResponse:
        try:
            with request.app.state.session_factory() as session:
                session.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
        return JSONResponse(content={"status": "ok", "database": "ok"})

    return application


app = create_app()
