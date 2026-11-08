from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers.chat import router

app = FastAPI(
    title="Freshgate",
    description="Freshness guard for answers that leave the Bifrost gateway.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Freshgate-Score", "X-Freshgate-Flagged", "X-Freshgate-Action"],
)

app.include_router(router)

# Same process serves the UI on Vercel and locally (API routes registered first).
if settings.frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(settings.frontend_dir), html=True), name="frontend")
