"""FastAPI application entrypoint.

Wires CORS, the versioned API router, and a health endpoint used to confirm
the backend is up and to report database connectivity. Domain feature routers
(auth, companies, transactions, ...) are registered here as they are built in
later phases.
"""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.companies.router import router as companies_router
from app.core.config import settings
from app.core.database import check_connection, dispose_engine

# Import every model module so all ORM classes are registered on the mapper
# registry before the first request. `User.companies` is a string-based
# relationship to `Company`; without importing the companies model here,
# SQLAlchemy can't resolve it and raises KeyError('Company') on flush/refresh.
import app.auth.models  # noqa: F401,E402
import app.companies.models  # noqa: F401,E402
import app.transactions.models  # noqa: F401,E402


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


api_router.include_router(auth_router)
api_router.include_router(companies_router)

app.include_router(api_router)


@app.get("/", tags=["health"])
async def root() -> dict:
    return {"status": "ok", "docs": "/docs", "health": f"{settings.api_v1_prefix}/health"}
