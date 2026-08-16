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

> **Current status: Phase 11 (background music) implemented and verified.**
> The full pipeline is built incrementally in phases — see [Roadmap](#roadmap).

---

## Features

Implemented:

- 6-service Docker stack, all images **linux/arm64 + linux/amd64**
- FastAPI backend with structured logging and typed configuration
- MySQL 8 (utf8mb4) and Redis 7 with health-gated startup
- `GET /api/health` probes API / MySQL / Redis; `GET /healthz` liveness
- React dashboard (system status, pipeline overview, Google Drive panel)
- Redis-connected worker with Drive inbox watcher
- Provider abstraction contracts: Storage / AI / Transcription / Publishing

Phase 2 (Google Drive):

- Google **OAuth 2.0** web flow with `state` validation (Redis) and
  **Fernet-encrypted** token storage — tokens never touch logs
- `GoogleDriveProvider`: resumable upload (verified by size + `md5Checksum`),
  streamed download, trash-safe delete, move, idempotent folder creation
- Auto-created Drive structure: `ClipForge/01_Inbox … 09_Metadata`
- SHA-256 checksums + `storage_files` registry (§49)
- Read videos from Drive: list inbox + download endpoints
- Worker `DriveWatcher` polls `01_Inbox` (`DRIVE_POLL_INTERVAL`)

Phase 3 (YouTube import):

- `POST /api/videos/import` validates YouTube URLs (watch / shorts / you.be)
- Minimal Redis job queue (§47) — imports are processed by the **worker**, not
  the HTTP request (§26)
- yt-dlp downloads best video+audio up to 1080p (matches the 1080×1920 render target), merged to MP4 with FFmpeg
- §13 metadata stored: title, description, channel, duration, resolution,
  fps, codec, filesize, thumbnail, checksum
- **Duplicate detection (§67)**: SHA-256 checksum — the same video is never
  downloaded or uploaded twice
- Original synced to Drive `02_Processing` (or local storage in dev), recorded
  in `storage_files`, then the local temp file is deleted (§28)

Phase 4 (Whisper transcription):

- **faster-whisper** (CTranslate2, int8) — realistic for Orange Pi 5 Pro 8 GB
  (§14); model files cached on the persistent `/data` volume (`HF_HOME`)
- `POST /api/videos/{id}/transcribe` → worker extracts 16 kHz audio (FFmpeg)
  → local Whisper → timestamped transcript
- Transcript **caching (§15)**: already-transcribed videos are never
  re-transcribed (idempotent)
- `GET /api/videos/{id}/transcript` — segments with start/end/confidence
- Local video files are kept for processing; retention cleanup per §68

Phase 5 (AI clip finder):

- `AIProvider` abstraction (§56): **DeepSeekProvider** (real API) +
  **MockAIProvider** (deterministic, `AI_PROVIDER=mock` — no key needed)
- `POST /api/videos/{id}/analyze` → worker `ANALYZE` job: transcript → AI
  candidates → **Pydantic validation with one retry (§18)**
- **§20 timestamp correction**: AI timestamps snap to sentence boundaries,
  never cut mid-sentence
- **§19 scoring**: `overall = hook·.25 + content·.20 + context·.15 +
  emotion·.10 + standalone·.15 + retention·.15`
- `clip_candidates` table + candidate UI with per-dimension scores,
  approve/reject (§31, §42); analysis cached per video (§55)

Phase 6 (renderer):

- `POST /api/candidates/{id}/render` → worker `RENDER` job: approved clip →
  9:16 Short with burned-in subtitles + hook text
- **Smart crop**: centered crop to the target 9:16 aspect (vertical slice
  for landscape, horizontal slice for tall/portrait), then scale to 1080×1920
  — never stretched or letterboxed
- **ASS subtitles**: transcript sentences inside the clip window burned in at
  the bottom (clip-relative timeline, overlapping segments merged); the AI
  **hook text** overlaid at the top for the whole clip
- **FFmpeg** renders with input seeking (fast on long videos), x264 + AAC,
  `+faststart`; args list — no shell (§51)
- **Quality gate**: output is verified with ffprobe (resolution, duration,
  non-empty) before the clip is marked `rendered`; failures keep the
  candidate `approved` for retry
- `clip_renders` table (Alembic 0005); dashboard shows render status and an
  inline 9:16 preview (`GET /api/renders/{id}/file`)

Phase 7 (Drive output):

- Rendered Shorts are synced to Drive **`04_Clips/<video_id>/clip-<candidate_id>.mp4`**
  right after the quality gate passes
- Upload recorded in `storage_files` (verified size + checksum, same path as
  Phase 3); `clip_renders.remote_path` (Alembic 0006) exposed via the render
  payload
- **Best-effort sync**: if Drive isn't connected the render still succeeds
  locally (preview keeps working) — the Short is synced when Drive is
  available; full retry semantics arrive with the Phase 10 job state machine
- Dashboard shows “Saved to Drive · 04_Clips/…” under the preview

Phase 8–9 (YouTube publishing):

- YouTube **OAuth 2.0** web flow (same pattern as Drive): `state` in Redis,
  **Fernet-encrypted** tokens, channel name resolved on connect
- `YouTubeProvider` — resumable upload to the YouTube Data API (raw HTTP,
  no extra dependency), verified by the returned video id
- `POST /api/renders/{id}/publish` → worker `PUBLISH` job; title/description
  default from the approved candidate
- **Scheduling**: YouTube-native `publishAt` (privacy forced to `private`,
  the API requirement) — the Short goes live automatically at the set time
- `publications` table (Alembic 0007): publication history (§65) with
  `youtube_video_id`, status (queued → uploading → published/scheduled),
  error codes; statuses self-heal after the publish time passes
- Dashboard YouTube panel (connect + channel), Publish button on rendered
  clips, “Watch on YouTube” link + scheduled time

Phase 10 (full automation — Drop & Forget):

- **Inbox auto-import**: drop a video into Drive `01_Inbox` — the watcher
  registers it and the worker downloads, checksums (duplicate detection
  still applies, §67) and moves it to `02_Processing`; no dashboard needed
- **Automatic chaining** (`AUTO_APPROVE=true`): download → transcribe →
  analyze → **auto-approve the best candidate** (only when its score ≥
  `AUTO_APPROVE_THRESHOLD`, default 85) → render; weaker clips stay for
  manual review
- **Auto-publish** (`YOUTUBE_AUTO_PUBLISH=true`): every successfully
  rendered Short gets a publication and is uploaded to YouTube
  automatically; the source video then shows `completed`
- **Resilient queue**: `MAX_CONCURRENT_JOBS` consumers (default 1 — Orange Pi
  friendly), and jobs that crash unexpectedly are retried up to
  `MAX_JOB_RETRIES` times with exponential backoff (5s → 10s → … → 5 min)

Phase 11 (background music):

- Optional music bed under the original audio of every rendered Short
  (`BACKGROUND_MUSIC=true`): one deterministic track per candidate — the
  same clip always re-renders identically, different clips cycle through
  the library
- Tracks are mixed at `BACKGROUND_MUSIC_VOLUME` (default 0.15) with FFmpeg
  `amix`; supported containers: mp3/wav/ogg/m4a/flac/aac/opus
- **Graceful degradation**: no tracks, or a corrupt track, never fails a
  render — the Short is produced without music (`render_music_fallback`)

Planned (later phases):

- (none — roadmap complete)

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

*Implemented (Phase 2).* ClipForge connects to Google Drive with OAuth 2.0 —
no Google password is ever stored. Access/refresh tokens are encrypted at
rest with Fernet (`TOKEN_ENCRYPTION_KEY`) and never appear in logs.

### 1. Google Cloud Console

1. Go to https://console.cloud.google.com → create/select a project.
2. **APIs & Services → Library** → enable the **Google Drive API**.
3. **APIs & Services → OAuth consent screen** → configure (External, add
   yourself as a test user).
4. **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   → application type **Web application**.
5. Add an authorized redirect URI:
   `http://localhost:8080/api/google-drive/callback`
   (or `http://<orange-pi-ip>/api/google-drive/callback`).

### 2. .env

```dotenv
GOOGLE_CLIENT_ID=<from step 4>
GOOGLE_CLIENT_SECRET=<from step 4>
GOOGLE_REDIRECT_URI=http://localhost:8080/api/google-drive/callback
FRONTEND_PUBLIC_URL=http://localhost:8080
TOKEN_ENCRYPTION_KEY=<generate below>
DRIVE_POLL_INTERVAL=60
```

Generate the token encryption key:

```bash
docker compose exec clipforge-api python -m app.core.crypto
# paste the printed key into TOKEN_ENCRYPTION_KEY in .env, then:
docker compose up -d --force-recreate clipforge-api clipforge-worker
```

### 3. Connect

Open the dashboard → **Google Drive** panel → **Connect Google Drive**.
After authorizing, ClipForge creates the folder structure
(`ClipForge/01_Inbox` … `09_Metadata`) on your Drive and starts watching the
inbox. Upload a video to `ClipForge/01_Inbox` — the worker logs
`drive_file_detected`; YouTube imports are synced to `02_Processing`.

## YouTube Import

*Implemented (Phase 3).* Paste any YouTube URL (watch, Shorts, or you.be)
into the dashboard **YouTube import** panel (or call the API):

```bash
curl -X POST http://localhost/api/videos/import \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=…"}'
```

The worker picks up the `DOWNLOAD_VIDEO` job and:

1. Fetches metadata (title, channel, duration, resolution, fps, codec…)
2. Downloads best video+audio (capped at 1080p) and merges to MP4 (FFmpeg)
3. Computes the SHA-256 checksum
4. **Skips if a video with the same checksum already imported** (§67)
5. Uploads the original to `ClipForge/02_Processing` and records it in
   `storage_files`
6. Deletes the local temp file — only after the upload verified (§28)

Track progress in the dashboard (status pills) or:

```bash
curl http://localhost/api/videos
curl http://localhost/api/videos/1
```

If a download fails, the video shows `failed` with an error code
(`DOWNLOAD_FAILED`, `DRIVE_UPLOAD_FAILED`, …). Note that YouTube may block
certain cloud/datacenter IPs — on the Orange Pi's home network this works
normally.

## DeepSeek Setup

*Implemented (Phase 5).* Clip analysis runs through the `AIProvider`
abstraction (§56). Two backends:

```dotenv
AI_PROVIDER=deepseek       # production: requires a key
DEEPSEEK_API_KEY=          # https://platform.deepseek.com → API Keys
DEEPSEEK_MODEL=deepseek-chat
MAX_CLIPS_PER_VIDEO=5
```

Or, for a demo/test run **without any API key**:

```dotenv
AI_PROVIDER=mock
```

Only transcript text is ever sent to the AI — never video frames (§55). The
pipeline is: **Analyze** (dashboard button or `POST /api/videos/{id}/analyze`)
→ AI returns JSON candidates (§18) → Pydantic validation (one retry) → §20
sentence-boundary correction → §19 overall score → candidates listed in the
dashboard with per-dimension scores and approve/reject (§31).

## Rendering Setup

*Implemented (Phase 6).* Approved candidates become 9:16 Shorts with
burned-in subtitles and the AI hook text. Rendering runs on the worker with
FFmpeg (installed in the image, plus DejaVu fonts for subtitles):

```dotenv
RENDER_WIDTH=1080
RENDER_HEIGHT=1920
RENDER_CRF=23            # lower = better quality, slower encode
RENDER_PRESET=veryfast   # Orange-Pi friendly
RENDER_AUDIO_BITRATE=128k
RENDER_QUALITY_CHECK=true
RENDER_TIMEOUT_SECONDS=1800
```

Click **Render** on any approved candidate in the dashboard (or
`POST /api/candidates/{id}/render`). The worker:

1. Locates the source video (kept locally or fetched back from Drive)
2. Smart-crops the clip window to 9:16 (centered crop, never stretched)
3. Burns in the hook text (top) + transcript subtitles (bottom) via ASS
4. Encodes x264/AAC with `+faststart` (input seeking — fast on long videos)
5. **Quality gate**: ffprobe verifies 1080×1920, duration and non-empty
   output; only then is the clip marked `rendered`

Preview the result inline (`GET /api/renders/{id}/file`). Failed renders keep
the candidate `approved` so you can retry. Renders are cached — a rendered
clip is never re-rendered.

### Background music (Phase 11)

Optional: mix a music track under the original audio of each Short.

```dotenv
BACKGROUND_MUSIC=true
BACKGROUND_MUSIC_PATH=/data/music   # empty = <TEMP_STORAGE_PATH>/music
BACKGROUND_MUSIC_VOLUME=0.15        # 0.0–1.0 relative level
```

Drop tracks (mp3/wav/ogg/m4a/flac/aac/opus) into the music directory. Each
candidate picks one track **deterministically** (same clip always
re-renders with the same track; different clips cycle through the library),
mixed under the original audio with FFmpeg `amix`. If the directory is empty
or a track fails to decode, the render falls back to no music — a bad track
never sinks a Short.

On the Orange Pi, add a bind mount so you can drop tracks from the host:

```yaml
# docker-compose.yml → clipforge-worker
volumes:
  - temp_data:/data
  - ./music:/data/music:ro
```

(set `BACKGROUND_MUSIC_PATH=/data/music` accordingly). Without a bind
mount, `docker compose cp track.mp3 clipforge-worker:/data/temp/music/`
works too (the file lives on the persistent `temp_data` volume).

## Whisper Setup

*Implemented (Phase 4).* Local transcription runs **faster-whisper**
(CTranslate2, int8) — built for low-RAM ARM devices like the Orange Pi 5 Pro
(§14). No API keys needed.

```dotenv
TRANSCRIPTION_PROVIDER=local
WHISPER_MODEL=base      # base (~140 MB) is the sweet spot for 8 GB RAM; small also fits
WHISPER_LANGUAGE=       # empty = auto-detect; set en/id for a specific language
```

The model downloads from Hugging Face on first use (into the persistent
`/data` volume) and is then cached. Transcribe from the dashboard
(**Transcribe** button on any downloaded video) or via the API:

```bash
curl -X POST http://localhost/api/videos/1/transcribe
curl http://localhost/api/videos/1/transcript   # cached, timestamped segments
```

Per §15, transcripts are cached — requesting transcription again is a no-op
("DO NOT TRANSCRIBE AGAIN").

## YouTube OAuth Setup

*Implemented (Phases 8–9).* Official YouTube Data API via OAuth 2.0 with
encrypted token storage. Default privacy is `private`; scheduling and
publication history included.

## First Run

1. `docker compose up -d` — wait until all containers report healthy
   (`docker compose ps`).
2. Open the dashboard and confirm **System status** shows API / MySQL / Redis
   all green.
3. Follow [Google Drive Setup](#google-drive-setup) to connect your account
   and start the inbox watcher.
4. Import a video: paste a YouTube URL into the dashboard, or drop a file
   into `ClipForge/01_Inbox` on Drive — both paths land in the video list.

## Automatic Mode

*Phase 10 — implemented.* With `AUTO_APPROVE=true` and
`YOUTUBE_AUTO_PUBLISH=true`, ClipForge becomes a **Drop & Forget** factory:
upload a video to the Drive inbox (or import a YouTube URL) and it is
downloaded, transcribed, analyzed, cropped, subtitled, rendered,
quality-checked, saved to Drive, and uploaded to YouTube — without opening
the dashboard.

```dotenv
AUTO_APPROVE=true          # run the pipeline end-to-end
AUTO_APPROVE_THRESHOLD=85  # only approve clips scoring >= this
YOUTUBE_AUTO_PUBLISH=true  # upload rendered Shorts to YouTube
YOUTUBE_DEFAULT_PRIVACY=private
```

How it works:

1. Drop a video into `ClipForge/01_Inbox` on Drive — the watcher registers it
   and the worker downloads it (checksum + duplicate detection still apply,
   §67), moves it to `02_Processing`, then starts the chain.
2. **Transcribe** → **Analyze** run automatically. From the AI candidates the
   worker auto-approves **only the best one**, and only when its overall
   score reaches `AUTO_APPROVE_THRESHOLD` — a weak analysis never ships
   itself; the clips stay in the dashboard for manual review instead.
3. The approved clip renders (9:16, subtitles, hook text, quality gate) and
   syncs to `04_Clips` as usual.
4. With `YOUTUBE_AUTO_PUBLISH=true` the Short is uploaded to YouTube
   automatically (privacy per `YOUTUBE_DEFAULT_PRIVACY`) and the source
   video is marked `completed`.

The pipeline is safe by default: `AUTO_APPROVE=false`,
`YOUTUBE_AUTO_PUBLISH=false` keep today's fully manual workflow. The
automation settings are shown on the dashboard under **Automatic mode**.

The worker also retries crashed jobs (`MAX_JOB_RETRIES=3` with exponential
backoff) and runs `MAX_CONCURRENT_JOBS` consumers — keep `1` on the Orange
Pi.

## Troubleshooting

| Symptom                          | Fix                                                                 |
| -------------------------------- | ------------------------------------------------------------------- |
| Port 80 bind error (Windows)     | Set `HTTP_PORT=8080` in `.env`, `docker compose up -d`              |
| MySQL stays unhealthy on first boot | First-time initialization takes ~30 s; check `docker compose logs clipforge-mysql` |
| `502` from `/api/*` after recreating API | `docker compose restart clipforge-nginx` (nginx caches upstream IPs) |
| Health shows `degraded`          | Check `docker compose logs clipforge-api`; confirm MySQL/Redis volumes are intact |
| Google Drive shows “Not connected” after restart | `TOKEN_ENCRYPTION_KEY` changed or unset — stored tokens can’t be decrypted; set the key and reconnect |
| Video failed with `TOKEN_DECRYPTION_FAILED` | The account was connected while `TOKEN_ENCRYPTION_KEY` was empty (tokens were stored under an ephemeral process key). Set the key in `.env`, recreate the containers, reconnect Drive/YouTube, and re-import — since v0.1 the API refuses to store tokens without a configured key |
| `GOOGLE_OAUTH_NOT_CONFIGURED`    | Fill `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` in `.env` and recreate the API container |
| Video stuck on `failed` + `DOWNLOAD_FAILED` | Network blocked YouTube (common on cloud IPs) or yt-dlp outdated: `docker compose exec clipforge-worker pip install -U yt-dlp`, then re-import |
| Inbox file never imported (`drive_file_ignored`) | Only video containers are imported (mp4/mov/mkv/webm/m4v/avi/mpeg/ts); rename or re-export the file |
| Nothing happens after dropping into the inbox | `AUTO_APPROVE=false` imports the video but stops there by design — transcribe/analyze manually, or enable automatic mode |
| Video stuck on `failed` + `TRANSCRIPTION_FAILED` | Check `docker compose logs clipforge-worker`; on low RAM use `WHISPER_MODEL=base`; the model downloads once on first transcribe (needs internet) |
| Clip stuck on `approved` / `RENDER_FAILED` | Check `docker compose logs clipforge-worker`; ffmpeg must be present (the image installs it); failed renders keep the candidate `approved` so you can retry |
| Memory pressure on Orange Pi     | Keep `MAX_CONCURRENT_JOBS=1` (Phase 5+); stop unused containers      |

## Roadmap

| Phase | Scope | Status |
| ----- | ----- | ------ |
| 1 | Foundation: Docker, FastAPI, MySQL, Redis, frontend, health | ✅ done |
| 2 | Google Drive: OAuth, folders, upload/download/move, checksum | ✅ done |
| 3 | YouTube import (yt-dlp) + metadata | ✅ done |
| 4 | Whisper transcription + caching | ✅ done |
| 5 | DeepSeek candidate analysis, scoring, candidate UI | ✅ done |
| 6 | Renderer: 9:16 crop, subtitles, hook text, quality check | ✅ done |
| 7 | Drive output of rendered shorts | ✅ done |
| 8–9 | YouTube OAuth, upload, scheduling, history | ✅ done |
| 10 | Full automation: Drive Inbox → published Short | ✅ done |
| 11 | Background music bed for Shorts | ✅ done |

## License

MIT — see [LICENSE](LICENSE).
