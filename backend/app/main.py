"""FastAPI application factory. Run with: uvicorn app.main:app --reload (from backend/)."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import health_router, v1
from .config import get_settings
from .errors import install_error_handlers


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NigahSense API",
        version="0.1.0",
        description="Incident API for the NigahSense first milestone. Times are UTC; clients display Asia/Karachi (PKT).",
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list(),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(v1)
    return app


app = create_app()
