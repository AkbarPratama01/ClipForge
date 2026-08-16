"""Transcription service — save/get/cache transcripts (§15).

Transcripts are cached per video: if a transcript already exists it is
returned as-is and never re-transcribed ("DO NOT TRANSCRIBE AGAIN").
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.transcription.models import Transcript, TranscriptSegment

logger = structlog.get_logger(__name__)


def get_transcript(
    db: Session, video_id: int
) -> tuple[Transcript, list[TranscriptSegment]] | None:
    transcript = (
        db.query(Transcript).filter(Transcript.video_id == video_id).first()
    )
    if transcript is None:
        return None
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.transcript_id == transcript.id)
        .order_by(TranscriptSegment.segment_index)
        .all()
    )
    return transcript, segments


def save_transcript(db: Session, video_id: int, result: dict) -> Transcript:
    """Persist a provider transcript result; idempotent (returns existing)."""
    existing = get_transcript(db, video_id)
    if existing is not None:
        logger.info("transcript_cached", video_id=video_id)
        return existing[0]

    transcript = Transcript(
        video_id=video_id,
        language=result.get("language"),
        model=settings.whisper_model,
        duration=result.get("duration"),
    )
    db.add(transcript)
    db.flush()

    for index, segment in enumerate(result.get("segments", [])):
        db.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                segment_index=index,
                start_time=segment["start"],
                end_time=segment["end"],
                text=segment["text"],
                confidence=segment.get("confidence"),
                speaker=segment.get("speaker"),
            )
        )

    db.commit()
    db.refresh(transcript)
    logger.info(
        "transcript_saved",
        video_id=video_id,
        transcript_id=transcript.id,
        segments=len(result.get("segments", [])),
    )
    return transcript


def transcript_payload(video_id: int, result: tuple[Transcript, list[TranscriptSegment]]) -> dict:
    transcript, segments = result
    return {
        "video_id": video_id,
        "transcript": {
            "id": transcript.id,
            "language": transcript.language,
            "model": transcript.model,
            "duration": transcript.duration,
            "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
        },
        "segments": [
            {
                "start": seg.start_time,
                "end": seg.end_time,
                "text": seg.text,
                "confidence": seg.confidence,
                "speaker": seg.speaker,
            }
            for seg in segments
        ],
    }
