import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.database import engine, Base, ensure_database_schema

logger = logging.getLogger("kre8")

# Import all models to ensure they register on Base
import app.models.models

# Create tables and ensure columns exist
try:
    Base.metadata.create_all(bind=engine)
    ensure_database_schema(engine)
    logger.info("[Database] Schema synchronized successfully.")
except Exception as e:
    logger.warning("[Database] Initial schema synchronization warning (will retry on requests): %s", e)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Kre8 Content Creator Workspace & AI Pipeline API"
)

# Catch unexpected errors INSIDE the CORS layer (registered first = innermost), so the browser
# gets readable JSON with CORS headers instead of an opaque "Failed to fetch".
@app.middleware("http")
async def catch_unexpected_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on our side. Please try again."}
        )

# CORS: support kre8.com.ng, Vercel deployments, preview URLs, and localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"^https?://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from app.api import auth, profile, news, ai, content, ideas, scripts, tasks, notes, calendar, goals, social, seed

api_routers = [
    auth.router,
    profile.router,
    news.router,
    ai.router,
    content.router,
    ideas.router,
    scripts.router,
    tasks.router,
    notes.router,
    calendar.router,
    goals.router,
    social.router,
    seed.router
]

for router in api_routers:
    # Mount with standard /api prefix
    app.include_router(router, prefix=settings.API_V1_STR)
    # Also mount at root so requests without /api prefix succeed seamlessly
    app.include_router(router)

@app.get("/")
def root():
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "status": "healthy"
    }

@app.get("/health")
def health():
    return {"status": "ok"}
