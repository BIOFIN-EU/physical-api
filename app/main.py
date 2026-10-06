import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.settings import settings
from app.logging_config import setup_logging
from app.routers.endpoints import api_router
from app.core.db import SessionLocal, init_db
from app.core.seed_case_data_lookups import seed_case_data_lookups
from app.core.seed_bng import seed_bng_reference_data
from app.core.exceptions import AppError
from app.core.internal_auth import require_internal_secret
from app.services.object_storage_service import ensure_bucket_exists


setup_logging()
logger = logging.getLogger(__name__)



@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_bucket_exists()

    await init_db()

    async with SessionLocal() as session:
        await seed_case_data_lookups(session)

    async with SessionLocal() as session:
        await seed_bng_reference_data(session)

    logger.info("Database initialized and workflow lookups seeded.")
    if not settings.INTERNAL_API_SECRET:
        logger.error("INTERNAL_API_SECRET is not set: every request will be refused")
    yield


app = FastAPI(
    title="physical-api",
    lifespan=lifespan,
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.exception("Database integrity error", exc_info=exc)

    return JSONResponse(
        status_code=400,
        content={"detail": "Database constraint error."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(require_internal_secret)

app.include_router(api_router)