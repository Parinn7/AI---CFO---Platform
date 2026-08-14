"""FastAPI application entrypoint.

Wires CORS, the versioned API router, and a health endpoint used to confirm
the backend is up and to report database connectivity. Domain feature routers
(auth, companies, transactions, ...) are registered here as they are built in
later phases.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import check_connection, dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: nothing to warm up yet.
    yield
    # Shutdown: release DB connections cleanly.
    await dispose_engine()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix=settings.api_v1_prefix)


@api_router.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness + DB connectivity check.

    `database` is one of: connected | not_configured | unreachable.
    A missing/unreachable DB still returns 200 with status "ok" so the
    frontend can verify backend reachability before Postgres is provisioned.
    """
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "database": await check_connection(),
    }


app.include_router(api_router)


@app.get("/", tags=["health"])
async def root() -> dict:
    return {"status": "ok", "docs": "/docs", "health": f"{settings.api_v1_prefix}/health"}
