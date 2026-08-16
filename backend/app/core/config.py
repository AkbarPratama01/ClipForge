"""Application settings, loaded from environment / .env file."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed access to ClipForge configuration.

    Values are read from environment variables (and a local ``.env`` file when
    present). Naming is case-insensitive, e.g. ``APP_ENV`` -> ``app_env``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "ClipForge"
    app_version: str = "0.1.0"
    app_env: str = "development"
    app_debug: bool = True

    # Infrastructure
    database_url: str = (
        "mysql+pymysql://clipforge:clipforge@127.0.0.1:3306/clipforge?charset=utf8mb4"
    )
    redis_url: str = "redis://127.0.0.1:6379/0"

    # HTTP
    cors_origins: str = "http://localhost,http://localhost:5173"

    # Processing
    temp_storage_path: str = "/data/temp"
    temp_file_retention_hours: int = 24

    # Transcription (§14)
    transcription_provider: str = "local"
    whisper_model: str = "base"
    whisper_language: str = ""  # empty = auto-detect
    # Silero VAD (faster-whisper vad_filter) is OFF by default: its LSTM cell
    # state drifts unbounded on long non-speech passages (e.g. music intros),
    # after which it classifies everything as silence and returns an empty
    # transcript. Set WHISPER_VAD_FILTER=true to re-enable when fixed upstream.
    whisper_vad_filter: bool = False

    # AI analysis (§56)
    ai_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    max_clips_per_video: int = 5

    # Rendering (Phase 6)
    render_width: int = 1080
    render_height: int = 1920
    render_crf: int = 23
    render_preset: str = "veryfast"
    render_audio_bitrate: str = "128k"
    # Quality gate (§Phase 6): verify the rendered file with ffprobe before
    # marking the clip rendered.
    render_quality_check: bool = True
    render_timeout_seconds: int = 1800

    # Background music (Phase 11)
    background_music: bool = False
    # Directory with music tracks (mp3/wav/ogg/m4a/flac/aac/opus). Empty =
    # ``<temp_storage_path>/music``. The renderer picks one track
    # deterministically per candidate and mixes it under the original audio
    # at ``background_music_volume`` (0.0–1.0 relative gain).
    background_music_path: str = ""
    background_music_volume: float = 0.15

    # YouTube publishing (Phase 8-9)
    publishing_provider: str = "youtube"
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = ""
    # Videos uploaded without an explicit privacy choice use this value.
    youtube_default_privacy: str = "private"

    # Automation (Phase 10 — Drop & Forget)
    # With AUTO_APPROVE=true the worker chains download → transcribe → analyze
    # → auto-approve → render without dashboard interaction.
    auto_approve: bool = False
    # A candidate is auto-approved only when its §19 overall score reaches this
    # value; otherwise it is left for manual review.
    auto_approve_threshold: int = 85
    # With YOUTUBE_AUTO_PUBLISH=true every successfully rendered Short is
    # uploaded automatically (privacy per youtube_default_privacy).
    youtube_auto_publish: bool = False

    # Worker (Phase 10)
    # How many jobs may run at once (keep 1 on Orange Pi 8 GB, §47) and how
    # many times an unexpectedly failing job is retried with backoff.
    max_concurrent_jobs: int = 1
    max_job_retries: int = 3

    # Storage / Google Drive (Phase 2)
    storage_provider: str = "google_drive"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_drive_root_folder: str = "ClipForge"
    drive_poll_interval: int = 60
    # Fernet key (base64, 32 bytes) used to encrypt OAuth tokens at rest.
    # Generate with: docker compose exec clipforge-api python -m app.core.crypto
    token_encryption_key: str | None = None
    # Where the OAuth callback redirects the browser after connecting.
    frontend_public_url: str = "http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
