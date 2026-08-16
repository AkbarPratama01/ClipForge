# syntax=docker/dockerfile:1
# ------------------------------------------------------------------------------
# ClipForge backend image — shared by the `clipforge-api` and `clipforge-worker`
# services. python:3.11-slim publishes linux/amd64 and linux/arm64.
# ------------------------------------------------------------------------------

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    HF_HOME=/data/models

WORKDIR /app

# FFmpeg: used by yt-dlp to merge best video+audio streams (Phase 3) and by
# the renderer (Phase 6). Debian bookworm publishes linux/arm64 builds.
# fonts-dejavu-core provides the Sans font used for burned-in ASS subtitles.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so this layer is cached across rebuilds.
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY backend/ /app/
COPY worker/ /app/worker/

# Temporary processing area + Whisper model cache. Named volumes inherit
# this ownership on first mount so the unprivileged user can read/write them.
RUN mkdir -p /data/temp /data/models && chown -R nobody:nogroup /data && chmod -R 770 /data

USER nobody

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
