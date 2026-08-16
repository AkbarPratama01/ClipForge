# ClipForge — Architecture

**Status:** Phase 5 (AI clip finder) implemented on top of Phase 1–4.
Phases 6+ are designed below and implemented incrementally; every phase must
pass its acceptance check before the next one starts.

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

## 6. Job pipeline

Phase 3 ships a minimal Redis list queue (``DOWNLOAD_VIDEO`` only, consumed by
the worker). The full job state machine arrives in Phase 5: all heavy work
queued (`DOWNLOAD, SYNC_DRIVE, TRANSCRIBE, ANALYZE, RENDER,
UPLOAD_DRIVE, GENERATE_METADATA, UPLOAD_YOUTUBE, CLEANUP`) with priorities,
`MAX_CONCURRENT_JOBS=1` on Orange Pi, exponential-backoff retries, and
idempotency keys for Drive/YouTube uploads (§47, §63, §64).

## 7. Phase acceptance (done)

### Phase 1 — Foundation

- [x] Repo scaffolding per §76
- [x] Docker Compose: 6 services, all ARM64 images
- [x] FastAPI app with settings + structured logging
- [x] `GET /api/health` probes MySQL + Redis; `GET /healthz` liveness
- [x] MySQL 8 (utf8mb4) and Redis 7 running, health-gated startup
- [x] React dashboard skeleton served through nginx
- [x] Worker stub connected to Redis
- [x] `docker compose up -d` → all services healthy

### Phase 2 — Google Drive (§77)

- [x] OAuth 2.0 web flow (`connect` → Google → `callback`), `state` in Redis
- [x] OAuth tokens encrypted with Fernet (`TOKEN_ENCRYPTION_KEY`) at rest
- [x] `google_drive_accounts` + `storage_files` tables (Alembic 0001)
- [x] `GoogleDriveProvider`: resumable upload, streamed download, trash-safe
      delete, parent-aware move, idempotent folder creation, list, metadata
- [x] `LocalStorageProvider` + factory (`STORAGE_PROVIDER` switch)
- [x] Folder bootstrap `ClipForge/01_Inbox … 09_Metadata` (§8)
- [x] SHA-256 checksums; upload verified by size + Drive `md5Checksum` (§50)
- [x] `GET /api/google-drive/status` — connection + storage quota
- [x] `GET /api/google-drive/files` + `POST …/files/{id}/download` (Phase 2
      acceptance: ClipForge can read videos from Drive, recorded in DB)
- [x] DriveWatcher in the worker polls `01_Inbox` (`DRIVE_POLL_INTERVAL`),
      emits `drive_file_detected` events (§66)
- [x] Dashboard Google Drive panel: status, connect, inbox files

### Phase 3 — YouTube Import (§77)

- [x] URL validation (watch / shorts / you.be) + `POST /api/videos/import`
- [x] Minimal Redis job queue — imports processed by the worker (§26)
- [x] yt-dlp: best video+audio up to 1080p merged to MP4 (FFmpeg in the image)
- [x] §13 metadata: title, description, channel, duration, resolution, fps,
      codec, filesize, thumbnail, checksum
- [x] Duplicate detection by SHA-256 checksum (§67)
- [x] Original synced to Drive `02_Processing`, recorded in `storage_files`
      (Alembic 0002: `videos` table + `storage_files.video_id`)
- [x] Local temp cleaned up only after the upload verified (§28)
- [x] Dashboard YouTube import panel + video list
- [x] Acceptance: YouTube URL → Video → Google Drive

### Phase 4 — Whisper Transcription (§77)

- [x] faster-whisper (CTranslate2, int8) — realistic for 8 GB ARM devices
- [x] Model cache on persistent `/data` volume (`HF_HOME`), loaded once/process
- [x] `transcripts` + `transcript_segments` tables (Alembic 0003)
- [x] `TRANSCRIBE` job: locate local video → 16 kHz audio (ffmpeg) → Whisper
- [x] Transcript caching (§15) — never transcribe twice
- [x] `POST /api/videos/{id}/transcribe` + `GET /api/videos/{id}/transcript`
- [x] Segments: start/end/text/confidence/speaker (§15 example format)
- [x] Local videos kept for the pipeline; retention per §68
- [x] Dashboard Transcribe button + status
- [x] Acceptance: Video → Transcript

### Phase 5 — AI Clip Finder (§77)

- [x] `AIProvider` abstraction: DeepSeekProvider + MockAIProvider (§56)
- [x] Worker `ANALYZE` job — transcript → candidates (never video frames, §55)
- [x] Pydantic JSON validation with one retry (§18)
- [x] §20 sentence-boundary timestamp correction
- [x] §19 overall scoring formula
- [x] `clip_candidates` table (Alembic 0004) + candidate UI with
      per-dimension scores + approve/reject (§31, §42)
- [x] Analysis cached per video (§55)
- [x] Acceptance: Video → 5 candidates

### Phase 6 — Renderer (§77)

- [x] `RENDER` job: approved candidate → 9:16 Short (FFmpeg on the worker)
- [x] Smart crop: centered crop to the target 9:16 aspect, then scale to
      1080×1920 — never stretched or letterboxed (even dims for h264)
- [x] ASS burn-in: hook text (top, full clip) + transcript subtitles
      (bottom, clip-relative timeline, overlapping segments merged)
- [x] Input seeking (`-ss` before `-i`) + PTS normalization — fast on long
      videos, subtitles stay in sync
- [x] Args-list subprocess (no shell, §51); x264 + AAC, `+faststart`
- [x] Quality gate: ffprobe verification (resolution / duration / non-empty)
      before a clip is marked `rendered`; failures keep it `approved` for retry
- [x] `clip_renders` table (Alembic 0005), renders cached per candidate
- [x] `POST /api/candidates/{id}/render`, `GET …/render`, `GET
      /api/renders/{id}/file`; dashboard Render button + 9:16 preview
- [x] Fonts (fonts-dejavu-core) installed in the Docker image for ASS
- [x] Acceptance: approved candidate → verified 9:16 Short with subtitles

### Phase 7 — Drive Output (§77)

- [x] Rendered Short synced to Drive `04_Clips/<video_id>/clip-<candidate_id>.mp4`
- [x] Upload recorded in `storage_files` (provider id, remote path, size,
      checksum, video link) — same verified-upload path as Phase 3
- [x] `clip_renders.remote_path` (Alembic 0006) exposed via render payload
- [x] Best-effort sync: Drive not connected / upload fails → render stays
      `rendered` locally (preview keeps working), `render_drive_sync_skipped`
      logged; full retry semantics arrive with the Phase 10 job state machine
- [x] Dashboard shows “Saved to Drive · 04_Clips/…” under the preview
- [x] Acceptance: rendered Short → 04_Clips on Google Drive + storage_files row

## 8. Roadmap

| Phase | Scope                                            |
| ----- | ------------------------------------------------ |
| 2     | Google Drive OAuth, folder creation, upload/download/move, checksum | ✅ done |
| 3     | YouTube import via yt-dlp, metadata, Drive sync  | ✅ done |
| 4     | Whisper transcription + transcript caching       | ✅ done |
| 5     | Segmentation, DeepSeek candidate analysis, scoring, candidate UI | ✅ done |
| 6     | Renderer: 9:16 smart crop, subtitles, hook text, FFmpeg, quality check | ✅ done |
| 7     | Drive output of rendered shorts                  | ✅ done |
| 8–9   | YouTube OAuth, upload, scheduling, publication history | ✅ done |
| 10    | Full automation: Drive Inbox → published Short   | ✅ done |

See `README.md` for the full feature list and operating instructions.
