"""Abstract provider interfaces (contracts from the ClipForge design doc).

Phase 1 defines the contracts only. Concrete implementations arrive per phase:

- StorageProvider     -> GoogleDriveProvider / LocalStorageProvider / S3StorageProvider
- AIProvider          -> DeepSeekProvider / OpenAIProvider / MockAIProvider
- TranscriptionProvider -> LocalWhisperProvider / RemoteTranscriptionProvider
- PublishingProvider  -> YouTubeProvider / InstagramProvider / TikTokProvider
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Storage (§10, §58)
# ---------------------------------------------------------------------------

@dataclass
class StorageFile:
    """Uniform representation of a file on any storage backend."""

    id: str
    filename: str
    mime_type: str | None = None
    size: int | None = None
    checksum: str | None = None
    created_at: str | None = None
    metadata: dict = field(default_factory=dict)


class StorageProvider(ABC):
    """Persistent storage abstraction. Google Drive is the default backend."""

    @abstractmethod
    def upload(self, local_path: str, remote_path: str, mime_type: str | None = None) -> StorageFile:
        """Upload a local file to ``remote_path``; return the remote handle."""

    @abstractmethod
    def download(self, remote_path: str, local_path: str) -> str:
        """Download ``remote_path`` to ``local_path``; return the local path."""

    @abstractmethod
    def delete(self, remote_path: str) -> None:
        """Delete the remote object at ``remote_path``."""

    @abstractmethod
    def move(self, source: str, destination: str) -> None:
        """Move/rename a remote object (e.g. Inbox -> Processing -> Archive)."""

    @abstractmethod
    def create_folder(self, path: str) -> str:
        """Ensure a folder exists (idempotent); return its remote id."""

    @abstractmethod
    def list_files(self, path: str) -> list[StorageFile]:
        """List files directly under ``path``."""

    @abstractmethod
    def get_metadata(self, path: str) -> dict:
        """Return backend metadata for the object at ``path``."""

    def watch(self, path: str) -> None:
        """Set up push-based change notifications (optional; DriveWatcher uses
        polling when the backend cannot push)."""
        raise NotImplementedError(f"{type(self).__name__} does not support watch()")


# ---------------------------------------------------------------------------
# AI (§56)
# ---------------------------------------------------------------------------

class AIProvider(ABC):
    """Cloud AI analysis (DeepSeek by default). Used only for tasks that
    genuinely need an LLM — never for raw media processing."""

    @abstractmethod
    def analyze_transcript(self, transcript: dict) -> dict:
        """Return structured clip candidates with scores (JSON validated by Pydantic)."""

    @abstractmethod
    def rank_clips(self, clips: list[dict]) -> list[dict]:
        """Order candidates by overall score."""

    @abstractmethod
    def generate_metadata(self, clip: dict) -> dict:
        """Generate title / description / hashtags / tags for a clip."""

    @abstractmethod
    def generate_hook(self, clip: dict) -> str:
        """Generate a short hook text overlay (1-3 s)."""


# ---------------------------------------------------------------------------
# Transcription (§57)
# ---------------------------------------------------------------------------

class TranscriptionProvider(ABC):
    """Speech-to-text with word/sentence timestamps. Local Whisper by default."""

    @abstractmethod
    def transcribe(self, audio_path: str, language: str | None = None) -> dict:
        """Return a transcript document with ``segments`` (start, end, text,
        confidence, speaker)."""


# ---------------------------------------------------------------------------
# Publishing (§59)
# ---------------------------------------------------------------------------

class PublishingProvider(ABC):
    """Short-form platform publishing. YouTube is the MVP target."""

    @abstractmethod
    def publish(self, video_path: str, metadata: dict) -> dict:
        """Upload ``video_path`` with metadata; return the platform's external id."""

    @abstractmethod
    def status(self, external_id: str) -> dict:
        """Return publishing status for an external video id."""
