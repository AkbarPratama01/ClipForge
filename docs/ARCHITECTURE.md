# ClipForge — Architecture

**Status:** Phase 1 (Foundation) implemented. Phases 2+ are designed below and
implemented incrementally; every phase must pass its acceptance check before
the next one starts.

## 1. Overview

ClipForge turns long videos into high-quality YouTube Shorts automatically:

```text
YouTube URL / Google Drive Inbox
        ↓
    Import & Download (yt-dlp)
        ↓
    Transcribe (local Whisper)
        ↓
    AI analysis (DeepSeek) → scored candidates
        ↓
    Smart crop 9:16 + subtitles + hook text (FFmpeg)
        ↓
    Quality check → Google Drive (04_Clips)
        ↓
    Metadata → YouTube upload (OAuth 2.0)
        ↓
    Publication history
```

Design principle: **local-first**. Media processing runs on the device; the
cloud (DeepSeek, Google Drive, YouTube) is used only when genuinely needed.

## 2. Services (Docker Compose)

| Service            | Role                                             | Image / build          |
| ------------------ | ------------------------------------------------ | ---------------------- |
| `clipforge-nginx`  | Reverse proxy, single entry point (`:80`)        | `nginx:1.27-alpine`    |
| `clipforge-frontend` | React dashboard (SPA) served by nginx          | `frontend/Dockerfile`  |
| `clipforge-api`    | FastAPI application + `/api/health`              | `backend/Dockerfile`   |
| `clipforge-worker` | Heavy jobs (download/transcribe/analyze/render)  | `backend/Dockerfile`   |
| `clipforge-mysql`  | Primary database (utf8mb4)                       | `mysql:8.0`            |
| `clipforge-redis`  | Queue + cache                                    | `redis:7-alpine`       |

All images publish **linux/arm64** (Orange Pi 5 Pro) and **linux/amd64**.

```text
                         USER
                          │
                          ▼
                    WEB DASHBOARD
                          │
                          ▼
                       NGINX
                          │
                          ▼
                     FASTAPI API
                          │
             ┌────────────┼─────────────┐
             ▼            ▼             ▼
           MySQL        Redis        Google Drive
             │            │             │
             │            ▼             │
             │          Worker           │
             │            │             │
             │     ┌──────┼───────┐     │
             │     ▼      ▼       ▼     │
             │   yt-dlp Whisper FFmpeg  │
             │            │             │
             │            ▼             │
             │       DeepSeek API       │
             │            │             │
             └────────────┼─────────────┘
                          ▼
                    YouTube Data API
```

## 3. Backend layout

```text
backend/app/
├── core/        # Settings (pydantic-settings), structured logging
├── database/    # SQLAlchemy engine/session, declarative Base, Alembic
├── api/         # Routers; /api/health, /api/healthz (Phase 1)
├── modules/     # Feature modules (projects, videos, transcription, analysis,
│                #   clips, rendering, storage, publishing, jobs) — stubs now
└── providers/   # Provider interfaces (base.py) + ai/, transcription/,
                 #   storage/, publishing/ implementations (later phases)
```

### 4. Provider contracts (defined in `app/providers/base.py`)

- **StorageProvider** — `upload/download/delete/move/create_folder/list_files/get_metadata/watch`; default backend Google Drive (§10).
- **AIProvider** — `analyze_transcript/rank_clips/generate_metadata/generate_hook`; default DeepSeek (§56).
- **TranscriptionProvider** — `transcribe`; default local Whisper (§57).
- **PublishingProvider** — `publish/status`; MVP YouTube (§59).

Backends are swapped via `*_PROVIDER` environment variables; application code
never depends on a concrete backend.

## 5. Data flow & persistence

```text
Google Drive (persistent)
      ↓ download/sync
/data/temp/<project_id>/   (local processing)
      ↓ FFmpeg / Whisper / OpenCV
/data/temp/<project_id>/render/
      ↓ upload + checksum verify
Google Drive 04_Clips/…   (persistent)
      ↓ delete local temp file
```

Drive folders: `01_Inbox` → `02_Processing` → `03_Projects` (per-project
`original/ transcript/ candidates/ renders/ metadata/`) → `04_Clips` /
`07_Transcripts` / `09_Metadata` / `06_Archive` (§8, §9).

## 6. Job pipeline (planned, Phase 5+)

All heavy work is queued (`DOWNLOAD, SYNC_DRIVE, TRANSCRIBE, ANALYZE, RENDER,
UPLOAD_DRIVE, GENERATE_METADATA, UPLOAD_YOUTUBE, CLEANUP`) with priorities,
`MAX_CONCURRENT_JOBS=1` on Orange Pi, exponential-backoff retries, and
idempotency keys for Drive/YouTube uploads (§47, §63, §64).

## 7. Phase 1 acceptance (done)

- [x] Repo scaffolding per §76
- [x] Docker Compose: 6 services, all ARM64 images
- [x] FastAPI app with settings + structured logging
- [x] `GET /api/health` probes MySQL + Redis; `GET /healthz` liveness
- [x] MySQL 8 (utf8mb4) and Redis 7 running, health-gated startup
- [x] React dashboard skeleton served through nginx
- [x] Worker stub connected to Redis
- [x] `docker compose up -d` → all services healthy

## 8. Roadmap

| Phase | Scope                                            |
| ----- | ------------------------------------------------ |
| 2     | Google Drive OAuth, folder creation, upload/download/move, checksum |
| 3     | YouTube import via yt-dlp, metadata, Drive sync  |
| 4     | Whisper transcription + transcript caching       |
| 5     | Segmentation, DeepSeek candidate analysis, scoring, candidate UI |
| 6     | Renderer: 9:16 smart crop, subtitles, hook text, FFmpeg, quality check |
| 7     | Drive output of rendered shorts                  |
| 8–9   | YouTube OAuth, upload, scheduling, publication history |
| 10    | Full automation: Drive Inbox → published Short   |

See `README.md` for the full feature list and operating instructions.
