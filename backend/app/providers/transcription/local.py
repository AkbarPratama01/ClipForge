"""LocalWhisperProvider — faster-whisper (CTranslate2) on CPU (§14, §57).

Deliberately NOT openai-whisper/torch: faster-whisper uses CTranslate2 with
int8 quantization, which is dramatically faster and lighter on an Orange Pi 5
Pro (8 GB RAM). The model is loaded once per process and cached; the model
files themselves live under ``HF_HOME`` on the persistent ``/data`` volume.
"""

from __future__ import annotations

import math

import structlog
from faster_whisper import WhisperModel

from app.core.config import settings
from app.providers.base import TranscriptionProvider

logger = structlog.get_logger(__name__)

_model_cache: dict[str, WhisperModel] = {}


class LocalWhisperProvider(TranscriptionProvider):
    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or settings.whisper_model or "base"

    def _get_model(self) -> WhisperModel:
        if self._model_name not in _model_cache:
            logger.info("whisper_model_loading", model=self._model_name)
            _model_cache[self._model_name] = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type="int8",
            )
            logger.info("whisper_model_ready", model=self._model_name)
        return _model_cache[self._model_name]

    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        model = self._get_model()
        # language=None → auto-detect (§14). VAD skips silence, saving time,
        # but is disabled by default — see settings.whisper_vad_filter.
        segments_iter, info = model.transcribe(
            audio_path,
            language=language or None,
            vad_filter=settings.whisper_vad_filter,
            beam_size=5,
        )

        segments: list[dict] = []
        for segment in segments_iter:
            # avg_logprob is negative; map to a 0..1 confidence value.
            confidence = round(math.exp(min(float(segment.avg_logprob), 0.0)), 4)
            segments.append(
                {
                    "start": round(float(segment.start), 3),
                    "end": round(float(segment.end), 3),
                    "text": segment.text.strip(),
                    "confidence": confidence,
                    "speaker": None,
                }
            )

        result = {
            "language": info.language,
            "duration": round(float(info.duration), 3),
            "segments": segments,
        }
        logger.info(
            "transcription_provider_completed",
            model=self._model_name,
            language=result["language"],
            segments=len(segments),
        )
        return result
