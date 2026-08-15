# ClipForge

**Turn Long Videos Into Short-Form Content Automatically.**

ClipForge is a self-hosted system that converts long videos (YouTube URLs or
videos dropped into a Google Drive inbox) into high-quality YouTube Shorts —
with AI finding the best moments, smart 9:16 cropping, auto subtitles, and
automatic publishing. Designed to run on an **Orange Pi 5 Pro (8 GB RAM,
ARM64)** with Docker, and to require **zero coding or manual editing** after
initial setup.

```text
VIDEO PANJANG → CLIPFORGE → AI FINDS BEST MOMENTS → AUTO EDIT → SHORTS → GOOGLE DRIVE → YOUTUBE
```

> **Current status: Phase 1 (Foundation) is implemented and verified.** The
> full pipeline is built incrementally in phases — see [Roadmap](#roadmap).

---

## Features

Implemented (Phase 1):

- 6-service Docker stack, all images **linux/arm64 + linux/amd64**
- FastAPI backend with structured logging and typed configuration
- MySQL 8 (utf8mb4) and Redis 7 with health-gated startup
- `GET /api/health` probes API / MySQL / Redis; `GET /healthz` liveness
- React dashboard (system status, pipeline overview)
- Redis-connected worker process (stub — job queue arrives in Phase 5)
- Provider abstraction contracts: Storage / AI / Transcription / Publishing

Planned (later phases):

- Google Drive OAuth + persistent storage (`01_Inbox` … `09_Metadata` folders)
- YouTube URL import via yt-dlp, duplicate detection, checksums
- Local Whisper transcription with timestamped segments + caching
- DeepSeek clip analysis: hook/value/emotion/standalone scoring (§18–19)
- Smart crop 16:9 → 9:16, auto subtitles (ASS/SRT), hook text
- FFmpeg rendering with quality check; manual/auto approval
- YouTube OAuth upload with scheduling and publication history
- **Drop & Forget**: upload a video to the Drive inbox — ClipForge does the rest

## Architecture

```
                         USER
                          │
                          ▼
                    WEB DASHBOARD ──► NGINX ──► FASTAPI API
                                                    │
                                ┌───────────────────┼───────────────────┐
                                ▼                   ▼                   ▼
                              MySQL              Redis            Google Drive
                                │                   │                   │
                                │                 Worker                │
                                │                   │                   │
                                │          ┌────────┼────────┐          │
                                │          ▼        ▼        ▼          │
                                │       yt-dlp   Whisper   FFmpeg      │
                                │                   │                   │
                                │               DeepSeek API            │
                                └───────────────────┼───────────────────┘
                                                    ▼
                                              YouTube Data API
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Requirements

- Docker Engine **20.10+** with Docker Compose **v2** (Docker Desktop on
  Windows/macOS, Docker CE on Linux)
- ~4 GB free RAM for the stack (Orange Pi 5 Pro 8 GB is the target device)
- ARM64 (Orange Pi 5 / 5 Pro, Raspberry Pi 4/5) **or** x86_64 host
- Internet connection for image pulls and API access

## Installation

```bash
git clone <repository-url>
cd clipforge
cp .env.example .env        # or: ./scripts/setup_env.sh
# edit .env — change MYSQL_PASSWORD and MYSQL_ROOT_PASSWORD
docker compose up -d
```

Open **http://localhost** (or `http://<orange-pi-ip>`).

If port 80 is already in use (common on Windows), set a different port in
`.env`:

```dotenv
HTTP_PORT=8080
```

## Docker

| Service            | Purpose                                   |
| ------------------ | ----------------------------------------- |
| `clipforge-nginx`  | Reverse proxy — single entry point        |
| `clipforge-frontend` | React dashboard (nginx-served SPA)     |
| `clipforge-api`    | FastAPI application, `/api/health`        |
| `clipforge-worker` | Heavy jobs (download/transcribe/analyze/render) |
| `clipforge-mysql`  | Primary database                          |
| `clipforge-redis`  | Job queue + cache                         |

Useful commands:

```bash
docker compose ps                 # service health
docker compose logs -f clipforge-api
curl http://localhost/api/health  # readiness: api + mysql + redis
docker compose exec clipforge-api pytest   # backend tests
docker compose down               # stop (data volumes persist)
docker compose down -v            # stop AND delete data volumes
```

Database migrations are managed with Alembic:

```bash
docker compose exec clipforge-api alembic upgrade head
```

## Google Drive Setup

*Phase 2 — planned.* ClipForge will connect via OAuth 2.0 (no passwords
stored), auto-create the folder structure (`01_Inbox` … `09_Metadata`), and
use Drive as the persistent storage layer with checksum verification. Setup
will be driven from the dashboard settings page.

## DeepSeek Setup

*Phase 5 — planned.* Used only for clip analysis, ranking, metadata, and hook
generation (`DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL` in `.env`). All media
processing stays local.

## Whisper Setup

*Phase 4 — planned.* Local Whisper transcription (`TRANSCRIPTION_PROVIDER=local`,
`WHISPER_MODEL=base` recommended for 8 GB devices), with transcript caching so
already-transcribed videos are never re-transcribed.

## YouTube OAuth Setup

*Phases 8–9 — planned.* Official YouTube Data API via OAuth 2.0 with
encrypted token storage. Default privacy is `private`; scheduling and
publication history included.

## First Run

1. `docker compose up -d` — wait until all containers report healthy
   (`docker compose ps`).
2. Open the dashboard and confirm **System status** shows API / MySQL / Redis
   all green.
3. From Phase 2 onward, connect Google Drive and YouTube from the dashboard,
   then drop a video into `ClipForge/01_Inbox`.

## Automatic Mode

*Phase 10 — planned.* With `AUTO_APPROVE=true` and `YOUTUBE_AUTO_PUBLISH=true`,
ClipForge becomes a **Drop & Forget** factory: upload a video to the Drive
inbox and it is downloaded, transcribed, analyzed, cropped, subtitled,
rendered, quality-checked, saved to Drive, and uploaded to YouTube — without
opening the dashboard.

Safe defaults stay conservative: `AUTO_APPROVE=false`,
`YOUTUBE_DEFAULT_PRIVACY=private`, `YOUTUBE_AUTO_PUBLISH=false`.

## Troubleshooting

| Symptom                          | Fix                                                                 |
| -------------------------------- | ------------------------------------------------------------------- |
| Port 80 bind error (Windows)     | Set `HTTP_PORT=8080` in `.env`, `docker compose up -d`              |
| MySQL stays unhealthy on first boot | First-time initialization takes ~30 s; check `docker compose logs clipforge-mysql` |
| `502` from `/api/*` after recreating API | `docker compose restart clipforge-nginx` (nginx caches upstream IPs) |
| Health shows `degraded`          | Check `docker compose logs clipforge-api`; confirm MySQL/Redis volumes are intact |
| Memory pressure on Orange Pi     | Keep `MAX_CONCURRENT_JOBS=1` (Phase 5+); stop unused containers      |

## Roadmap

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1 | Foundation: Docker, FastAPI, MySQL, Redis, frontend, health | ✅ done |
| 2 | Google Drive: OAuth, folders, upload/download/move, checksum | planned |
| 3 | YouTube import (yt-dlp) + metadata | planned |
| 4 | Whisper transcription + caching | planned |
| 5 | DeepSeek candidate analysis, scoring, candidate UI | planned |
| 6 | Renderer: 9:16 crop, subtitles, hook text, quality check | planned |
| 7 | Drive output of rendered shorts | planned |
| 8–9 | YouTube OAuth, upload, scheduling, history | planned |
| 10 | Full automation: Drive Inbox → published Short | planned |

## License

MIT — see [LICENSE](LICENSE).
