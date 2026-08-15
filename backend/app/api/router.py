"""Aggregated API router. Feature modules mount their routers here as they
land in later phases (projects, videos, clips, publishing, jobs, ...)."""

from fastapi import APIRouter

from app.api.routes_health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
