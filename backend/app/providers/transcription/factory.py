"""Transcription provider factory (§14, §57) — ``TRANSCRIPTION_PROVIDER``."""

from __future__ import annotations

from app.core.config import settings
from app.providers.base import TranscriptionProvider


def get_transcription_provider() -> TranscriptionProvider:
    provider = settings.transcription_provider
    if provider == "local":
        from app.providers.transcription.local import LocalWhisperProvider

        return LocalWhisperProvider()

    raise ValueError(
        f"Unknown TRANSCRIPTION_PROVIDER={provider!r} (supported: local)"
    )
