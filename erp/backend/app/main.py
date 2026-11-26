"""Application factory. `app.main:app` is the ASGI entry point for uvicorn."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401  (complete metadata and model hooks before any mapper is used)
from app.core.config import DEFAULT_SECRET_KEY, Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import register_exception_handlers
from app.core.features import discover_features
from app.modules.auth.service import sync_permissions

logger = logging.getLogger(__name__)


def _sync_permissions(application: FastAPI) -> None:
    with application.state.session_factory() as session:
        sync_permissions(session, application.state.permissions)
        session.commit()


@asynccontextmanager
async def _lifespan(application: FastAPI) -> AsyncIterator[None]:
    await run_in_threadpool(_sync_permissions, application)
    yield
    application.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application: engine, session factory, error handlers, discovered feature routers.

    `settings` only overrides the wiring done here (database, features, CORS); request-time code such
    as token signing and file storage reads `get_settings()`.
    """
    settings = settings or get_settings()
    if settings.secret_key == DEFAULT_SECRET_KEY:
        logger.warning("ERP_SECRET_KEY is not set: tokens are signed with the public development key")
    # The interactive API documentation is a development aid (its page loads assets from a CDN).
    with_docs = settings.env != "production"
    application = FastAPI(
        title="ERP",
        docs_url="/api/docs" if with_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if with_docs else None,
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
