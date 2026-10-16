from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from inboxkeeper import __version__
from inboxkeeper.api.context import AppContext, ProviderFactory, gmail_provider_factory
from inboxkeeper.api.routes import account, actions, proposals, stats, sync
from inboxkeeper.api.security import OriginCheckMiddleware
from inboxkeeper.auth.google import GoogleAuth
from inboxkeeper.config import Settings, get_settings
from inboxkeeper.db.session import create_db_engine


def create_app(
    settings: Settings | None = None,
    *,
    auth: GoogleAuth | None = None,
    provider_factory: ProviderFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    auth = auth or GoogleAuth(settings.data_dir)
    engine = create_db_engine(settings.db_path)

    app = FastAPI(title="inboxkeeper", version=__version__)
    app.state.ctx = AppContext(
        settings, engine, auth, provider_factory or gmail_provider_factory(auth)
    )

    # Middleware runs bottom-up: host check first, then origin, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.cors_origins)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(account.router)
    app.include_router(sync.router)
    app.include_router(stats.router)
    app.include_router(actions.router)
    app.include_router(proposals.router)
    return app
