"""Automation status endpoint (Phase 10).

Exposes the effective automatic-mode settings so the dashboard can tell the
operator whether ClipForge is in Drop & Forget mode (``auto_approve``) and
whether rendered Shorts are published automatically (``youtube_auto_publish``)
— and the score threshold used for auto-approval.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter(prefix="/automation", tags=["automation"])


@router.get("/status", summary="Automatic mode configuration")
def automation_status() -> JSONResponse:
    return JSONResponse(
        {
            "auto_approve": settings.auto_approve,
            "auto_approve_threshold": settings.auto_approve_threshold,
            "youtube_auto_publish": settings.youtube_auto_publish,
        }
    )
