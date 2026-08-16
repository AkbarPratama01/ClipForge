"""Aggregated API router. Feature modules mount their routers here as they
land in later phases (projects, videos, clips, publishing, jobs, ...)."""

from fastapi import APIRouter

from app.api.routes_health import router as health_router
from app.modules.analysis.routes import router as analysis_router
from app.modules.automation.routes import router as automation_router
from app.modules.publishing.routes import router as publishing_router
from app.modules.publishing.routes import youtube_router
from app.modules.rendering.routes import router as rendering_router
from app.modules.storage.routes import router as storage_router
from app.modules.transcription.routes import router as transcription_router
from app.modules.videos.routes import router as videos_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(storage_router)
api_router.include_router(videos_router)
api_router.include_router(transcription_router)
api_router.include_router(analysis_router)
api_router.include_router(rendering_router)
api_router.include_router(publishing_router)
api_router.include_router(youtube_router)
api_router.include_router(automation_router)
