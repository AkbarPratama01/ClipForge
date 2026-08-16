import { Fragment, type FormEvent, useEffect, useState } from "react";
import {
  analyzeVideo,
  connectDrive,
  connectYouTube,
  disconnectDrive,
  disconnectYouTube,
  fetchAutomationStatus,
  fetchCandidates,
  fetchDriveFiles,
  fetchDriveStatus,
  fetchHealth,
  fetchPublications,
  fetchRenderStatus,
  fetchVideos,
  fetchYouTubeStatus,
  importVideo,
  publishRender,
  renderCandidate,
  renderFileUrl,
  setCandidateStatus,
  transcribeVideo,
  type AutomationStatus,
  type Candidate,
  type DriveFile,
  type DriveStatus,
  type HealthResponse,
  type Publication,
  type RenderStatus,
  type VideoSummary,
  type YouTubeStatus,
} from "./api";

const STATS = [
  { label: "Videos processing", value: 0 },
  { label: "Shorts generated", value: 0 },
  { label: "Shorts published", value: 0 },
  { label: "Queue", value: 0 },
  { label: "Failed", value: 0 },
];

const SERVICE_LABELS: Record<string, string> = {
  api: "API",
  mysql: "MySQL",
  redis: "Redis",
};

function formatBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  const digits = value >= 10 || i === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[i]}`;
}

function Logo() {
  return (
    <div className="logo">
      <svg
        className="logo-mark"
        width="26"
        height="26"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M4 6.5 12 3l8 3.5v9L12 21l-8-3.5v-11Z"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
        <path
          d="M4 6.5 12 10l8-3.5M12 10v11"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinejoin="round"
        />
      </svg>
      <span className="logo-text">
        Clip<span>Forge</span>
      </span>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone =
    status === "ok" ||
    status === "downloaded" ||
    status === "uploaded" ||
    status === "completed" ||
    status === "rendered" ||
    status === "published"
      ? "ok"
      : status === "degraded" ||
          status === "warning" ||
          status === "pending" ||
          status === "downloading" ||
          status === "queued" ||
          status === "rendering" ||
          status === "uploading" ||
          status === "scheduled"
        ? "warn"
        : status === "error" || status === "failed" || status === "duplicate"
          ? "err"
          : "neutral";
  return (
    <span className={`pill pill-${tone}`}>
      <span className="dot" aria-hidden="true" />
      {status}
    </span>
  );
}

interface HealthSectionProps {
  health: HealthResponse | null;
  error: string | null;
  updatedAt: number | null;
}

function HealthSection({ health, error, updatedAt }: HealthSectionProps) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>System status</h2>
        {updatedAt ? (
          <span className="muted small">
            updated {new Date(updatedAt).toLocaleTimeString()}
          </span>
        ) : null}
      </div>

      {error ? (
        <div className="empty">
          <p className="err-text">Cannot reach the API — {error}</p>
          <p className="muted small">
            Start the stack with <code>docker compose up -d</code>.
          </p>
        </div>
      ) : health ? (
        <ul className="status-list">
          {Object.entries(health.services).map(([key, svc]) => (
            <li key={key} className="status-row">
              <span className="status-name">{SERVICE_LABELS[key] ?? key}</span>
              <span className="status-meta muted small">
                {svc.latency_ms != null ? `${svc.latency_ms} ms` : "—"}
              </span>
              <StatusPill status={svc.status} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted small">Checking…</p>
      )}
    </section>
  );
}

function AutomationPanel() {
  const [status, setStatus] = useState<AutomationStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await fetchAutomationStatus();
        if (!cancelled) setStatus(s);
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const on = status?.auto_approve || status?.youtube_auto_publish;

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Automatic mode</h2>
        <span className="muted small">Drop &amp; Forget</span>
      </div>

      {status ? (
        <ul className="status-list">
          <li className="status-row">
            <span className="status-name">Pipeline</span>
            <StatusPill status={on ? "ok" : "pending"} />
          </li>
          <li className="status-row">
            <span className="status-name muted small">
              auto-approve best clip ≥ {status.auto_approve_threshold}
            </span>
            <StatusPill status={status.auto_approve ? "ok" : "neutral"} />
          </li>
          <li className="status-row">
            <span className="status-name muted small">auto-publish to YouTube</span>
            <StatusPill status={status.youtube_auto_publish ? "ok" : "neutral"} />
          </li>
        </ul>
      ) : (
        <p className="muted small">
          Set <code>AUTO_APPROVE</code> / <code>YOUTUBE_AUTO_PUBLISH</code> in
          .env to enable the unattended pipeline.
        </p>
      )}
    </section>
  );
}

function DrivePanel() {
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [files, setFiles] = useState<DriveFile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("drive") === "connected") {
      setNotice("Google Drive connected successfully.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("drive") === "error") {
      setNotice("Google Drive connection failed or was cancelled.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await fetchDriveStatus();
        if (cancelled) return;
        setStatus(s);
        if (s.connected) {
          try {
            const f = await fetchDriveFiles();
            if (!cancelled) setFiles(f.files);
          } catch {
            if (!cancelled) setFiles([]);
          }
        } else {
          setFiles(null);
        }
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const connect = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const { auth_url } = await connectDrive();
      window.location.href = auth_url;
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Connection failed.");
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setNotice(null);
    try {
      await disconnectDrive();
      setStatus({ connected: false });
      setFiles(null);
      setNotice("Google Drive disconnected — token removed.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Disconnect failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Google Drive</h2>
        <span className="muted small">Drop &amp; Forget inbox</span>
      </div>

      {notice ? <p className="notice">{notice}</p> : null}

      {status?.connected ? (
        <>
          <ul className="status-list">
            <li className="status-row">
              <span className="status-name">Account</span>
              <span className="status-meta muted small">
                {status.email ?? "connected"}
              </span>
              <StatusPill status="ok" />
            </li>
            {status.storage_limit != null ? (
              <li className="status-row">
                <span className="status-name">Drive storage</span>
                <span className="status-meta muted small">
                  {formatBytes(status.storage_used)} /{" "}
                  {formatBytes(status.storage_limit)}
                </span>
              </li>
            ) : null}
          </ul>

          <div className="panel-actions">
            <button
              className="btn btn-mini btn-danger"
              onClick={() => void disconnect()}
              disabled={busy}
            >
              {busy ? "…" : "Disconnect"}
            </button>
          </div>

          <div className="drive-files">
            <p className="muted small drive-files-title">
              Inbox — {files?.length ?? 0} file{files?.length === 1 ? "" : "s"}
            </p>
            {files && files.length > 0 ? (
              <ul className="file-list">
                {files.slice(0, 5).map((f) => (
                  <li key={f.id} className="file-row">
                    <span className="file-name">{f.filename}</span>
                    <span className="muted small">{formatBytes(f.size)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted small">
                Drop a video into <code>ClipForge/01_Inbox</code> — the watcher
                picks it up automatically.
              </p>
            )}
          </div>
        </>
      ) : (
        <div className="empty">
          <p className="muted">Not connected.</p>
          <p className="muted small">
            Connect your Google account to use Drive as persistent storage.
          </p>
          <button className="btn" onClick={connect} disabled={busy}>
            {busy ? "Connecting…" : "Connect Google Drive"}
          </button>
        </div>
      )}
    </section>
  );
}

function YouTubePanel() {
  const [status, setStatus] = useState<YouTubeStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("youtube") === "connected") {
      setNotice("YouTube connected successfully.");
      window.history.replaceState({}, "", window.location.pathname);
    } else if (params.get("youtube") === "error") {
      setNotice("YouTube connection failed or was cancelled.");
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const s = await fetchYouTubeStatus();
        if (!cancelled) setStatus(s);
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    void load();
    const id = window.setInterval(load, 30_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const connect = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const { auth_url } = await connectYouTube();
      window.location.href = auth_url;
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Connection failed.");
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    setNotice(null);
    try {
      await disconnectYouTube();
      setStatus({ connected: false });
      setNotice("YouTube disconnected — token removed.");
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "Disconnect failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>YouTube</h2>
        <span className="muted small">publish Shorts</span>
      </div>

      {notice ? <p className="notice">{notice}</p> : null}

      {status?.connected ? (
        <>
          <ul className="status-list">
            <li className="status-row">
              <span className="status-name">Channel</span>
              <span className="status-meta muted small">
                {status.channel_name ?? "connected"}
              </span>
              <StatusPill status="ok" />
            </li>
          </ul>
          <div className="panel-actions">
            <button
              className="btn btn-mini btn-danger"
              onClick={() => void disconnect()}
              disabled={busy}
            >
              {busy ? "…" : "Disconnect"}
            </button>
          </div>
        </>
      ) : (
        <div className="empty">
          <p className="muted">Not connected.</p>
          <p className="muted small">
            Connect your channel to publish rendered Shorts with scheduling
            and publication history.
          </p>
          <button className="btn" onClick={connect} disabled={busy}>
            {busy ? "Connecting…" : "Connect YouTube"}
          </button>
        </div>
      )}
    </section>
  );
}

function fmtRange(start: number, end: number): string {
  const fmt = (s: number) =>
    `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`;
  return `${fmt(start)}–${fmt(end)}`;
}

function fmtDur(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}

function VideosPanel() {
  const [videos, setVideos] = useState<VideoSummary[] | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [transcribingId, setTranscribingId] = useState<number | null>(null);
  const [analyzingId, setAnalyzingId] = useState<number | null>(null);
  const [renderingId, setRenderingId] = useState<number | null>(null);
  const [publishingId, setPublishingId] = useState<number | null>(null);
  const [cands, setCands] = useState<Record<number, Candidate[]>>({});
  const [renders, setRenders] = useState<Record<number, RenderStatus>>({});
  const [pubs, setPubs] = useState<Record<number, Publication[]>>({});
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(
    null,
  );

  const loadCandidatesFor = async (list: VideoSummary[]) => {
    const analyzed = list.filter((v) => v.status === "analyzed");
    const next: Record<number, Candidate[]> = {};
    const nextRenders: Record<number, RenderStatus> = {};
    const nextPubs: Record<number, Publication[]> = {};
    await Promise.all(
      analyzed.map(async (v) => {
        try {
          const candidates = await fetchCandidates(v.id);
          next[v.id] = candidates;
          if (candidates.some((c) => c.status === "rendered")) {
            try {
              nextPubs[v.id] = await fetchPublications(v.id);
            } catch {
              nextPubs[v.id] = [];
            }
          }
          await Promise.all(
            candidates
              .filter((c) => c.status === "rendering" || c.status === "rendered")
              .map(async (c) => {
                try {
                  const r = await fetchRenderStatus(c.id);
                  if (r) nextRenders[c.id] = r;
                } catch {
                  /* render status unavailable — keep whatever we have */
                }
              }),
          );
        } catch {
          next[v.id] = [];
        }
      }),
    );
    setCands(next);
    setRenders((prev) => ({ ...prev, ...nextRenders }));
    setPubs((prev) => ({ ...prev, ...nextPubs }));
  };
  useEffect(() => {
    let cancelled = false;
    let intervalId: number | undefined;
    const load = async () => {
      let downloading = false;
      try {
        const list = await fetchVideos();
        if (!cancelled) {
          setVideos(list);
          void loadCandidatesFor(list);
          downloading = list.some((v) => v.status === "downloading");
        }
      } catch {
        if (!cancelled) setVideos(null);
      }
      if (!cancelled) {
        // Poll faster while a download is in flight so the percentage bar
        // updates smoothly; settle back to 15s otherwise.
        if (intervalId) window.clearInterval(intervalId);
        intervalId = window.setInterval(load, downloading ? 5_000 : 15_000);
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (intervalId) window.clearInterval(intervalId);
    };
  }, []);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setNotice(null);
    try {
      const result = await importVideo(trimmed);
      setNotice({
        kind: "ok",
        text: result.message ?? `Import queued (video #${result.video_id}).`,
      });
      setUrl("");
      setVideos(await fetchVideos());
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Import failed.",
      });
    } finally {
      setBusy(false);
    }
  };

  const transcribe = async (videoId: number) => {
    setTranscribingId(videoId);
    setNotice(null);
    try {
      const r = await transcribeVideo(videoId);
      setNotice({
        kind: "ok",
        text:
          r.status === "already_transcribed"
            ? "Already transcribed — transcript is cached (§15)."
            : (r.message ?? `Transcription queued for video #${videoId}.`),
      });
      setVideos(await fetchVideos());
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Transcription failed.",
      });
    } finally {
      setTranscribingId(null);
    }
  };

  const analyze = async (videoId: number) => {
    setAnalyzingId(videoId);
    setNotice(null);
    try {
      const r = await analyzeVideo(videoId);
      setNotice({
        kind: "ok",
        text:
          r.status === "already_analyzed"
            ? "Candidates already exist — analysis is cached (§55)."
            : (r.message ?? `Analysis queued for video #${videoId}.`),
      });
      const list = await fetchVideos();
      setVideos(list);
      void loadCandidatesFor(list);
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Analysis failed.",
      });
    } finally {
      setAnalyzingId(null);
    }
  };

  const decide = async (candidate: Candidate, action: "approve" | "reject") => {
    try {
      await setCandidateStatus(candidate.id, action);
      const refreshed = await fetchCandidates(candidate.video_id);
      setCands((prev) => ({ ...prev, [candidate.video_id]: refreshed }));
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Action failed.",
      });
    }
  };

  const render = async (candidate: Candidate) => {
    setRenderingId(candidate.id);
    setNotice(null);
    try {
      const r = await renderCandidate(candidate.id);
      setNotice({
        kind: "ok",
        text:
          r.status === "already_rendered"
            ? "Clip already rendered — the render is cached."
            : (r.message ?? `Render queued for clip #${candidate.id}.`),
      });
      const refreshed = await fetchCandidates(candidate.video_id);
      setCands((prev) => ({ ...prev, [candidate.video_id]: refreshed }));
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Render failed.",
      });
    } finally {
      setRenderingId(null);
    }
  };

  const publish = async (renderId: number) => {
    setPublishingId(renderId);
    setNotice(null);
    try {
      const r = await publishRender(renderId);
      setNotice({
        kind: "ok",
        text: r.message ?? `Publication queued (#${r.publication_id}).`,
      });
      const list = await fetchVideos();
      setVideos(list);
      void loadCandidatesFor(list);
    } catch (err) {
      setNotice({
        kind: "err",
        text: err instanceof Error ? err.message : "Publish failed.",
      });
    } finally {
      setPublishingId(null);
    }
  };

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>YouTube import</h2>
        <span className="muted small">worker downloads &amp; syncs to Drive</span>
      </div>

      <form className="import-form" onSubmit={submit}>
        <input
          className="import-input"
          type="url"
          placeholder="https://www.youtube.com/watch?v=…"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          disabled={busy}
          aria-label="YouTube URL"
        />
        <button className="btn btn-inline" type="submit" disabled={busy}>
          {busy ? "Importing…" : "Import"}
        </button>
      </form>

      {notice ? <p className={`notice notice-${notice.kind}`}>{notice.text}</p> : null}

      <div className="drive-files">
        <p className="muted small drive-files-title">
          Videos ({videos?.length ?? 0})
        </p>
        {videos && videos.length > 0 ? (
          <ul className="file-list">
            {videos.slice(0, 6).map((v) => (
              <Fragment key={v.id}>
                <li className="file-row">
                <span className="file-name">
                  {v.title ?? v.source_url}
                  {v.channel ? (
                    <span className="muted small"> — {v.channel}</span>
                  ) : null}
                </span>
                <span className="row-actions">
                  {["downloaded", "uploaded"].includes(v.status) ? (
                    <button
                      className="btn btn-mini"
                      onClick={() => void transcribe(v.id)}
                      disabled={transcribingId === v.id}
                    >
                      {transcribingId === v.id ? "…" : "Transcribe"}
                    </button>
                  ) : null}
                  {v.status === "transcribed" ? (
                    <button
                      className="btn btn-mini"
                      onClick={() => void analyze(v.id)}
                      disabled={analyzingId === v.id}
                    >
                      {analyzingId === v.id ? "…" : "Analyze"}
                    </button>
                  ) : null}
                  {v.status === "downloading" ? (
                    <span
                      className="dl-wrap"
                      title={`Download ${Math.round(v.download_progress ?? 0)}%`}
                    >
                      <span className="progress-track">
                        <span
                          className="progress-fill"
                          style={{
                            width: `${Math.min(100, Math.max(0, v.download_progress ?? 0))}%`,
                          }}
                        />
                      </span>
                      <span className="muted small dl-pct">
                        {Math.round(v.download_progress ?? 0)}%
                      </span>
                    </span>
                  ) : null}
                  <StatusPill status={v.status} />
                </span>
              </li>
              {cands[v.id] && cands[v.id].length > 0 ? (
                <li key={`${v.id}-cands`} className="cand-block">
                  {cands[v.id].slice(0, 4).map((c) => (
                    <div key={c.id} className="cand-row">
                      <div className="cand-main">
                        <span className="cand-title">{c.title}</span>
                        <span className="muted small">
                          {fmtRange(c.start_time, c.end_time)}
                        </span>
                      </div>
                      <span
                        className="score-badge"
                        title={`Hook ${c.hook_score} · Content ${c.content_score} · Context ${c.context_score} · Emotion ${c.emotion_score} · Standalone ${c.standalone_score} · Retention ${c.retention_score}`}
                      >
                        {c.score}
                      </span>
                      <span className="row-actions">
                        {c.status === "candidate" ? (
                          <>
                            <button
                              className="btn btn-mini btn-ok"
                              onClick={() => void decide(c, "approve")}
                              title="Approve"
                            >
                              ✓
                            </button>
                            <button
                              className="btn btn-mini btn-danger"
                              onClick={() => void decide(c, "reject")}
                              title="Reject"
                            >
                              ✕
                            </button>
                          </>
                        ) : c.status === "approved" ? (
                          <button
                            className="btn btn-mini"
                            onClick={() => void render(c)}
                            disabled={renderingId === c.id}
                            title="Render 9:16 Short with subtitles"
                          >
                            {renderingId === c.id ? "…" : "Render"}
                          </button>
                        ) : c.status === "rendering" ? (
                          <span className="muted small">Rendering…</span>
                        ) : (
                          <StatusPill status={c.status} />
                        )}
                      </span>
                      {renders[c.id] && renders[c.id].status === "rendered" ? (
                        <div className="render-preview">
                          <video
                            className="video-preview"
                            src={renderFileUrl(renders[c.id].id)}
                            controls
                            preload="metadata"
                          />
                          <span className="muted small render-meta">
                            {formatBytes(renders[c.id].filesize)} ·{" "}
                            {fmtDur(renders[c.id].duration ?? 0)}
                            {renders[c.id].remote_path ? (
                              <span className="render-drive">
                                Saved to Drive · {renders[c.id].remote_path}
                              </span>
                            ) : null}
                            <button
                              className="btn btn-mini"
                              onClick={() => void publish(renders[c.id].id)}
                              disabled={publishingId === renders[c.id].id}
                              title="Upload to YouTube"
                            >
                              {publishingId === renders[c.id].id ? "…" : "Publish"}
                            </button>
                          </span>
                        </div>
                      ) : null}
                      {(pubs[v.id] ?? [])
                        .filter((p) => p.render_id === renders[c.id]?.id)
                        .slice(0, 1)
                        .map((p) => (
                          <div key={p.id} className="pub-row">
                            <StatusPill status={p.status} />
                            {p.youtube_video_id ? (
                              <a
                                className="pub-link"
                                href={`https://www.youtube.com/watch?v=${p.youtube_video_id}`}
                                target="_blank"
                                rel="noreferrer"
                              >
                                youtube.com/watch?v={p.youtube_video_id}
                              </a>
                            ) : p.error_code ? (
                              <span className="muted small">{p.error_code}</span>
                            ) : null}
                            {p.scheduled_at ? (
                              <span className="muted small">
                                · {new Date(p.scheduled_at).toLocaleString()}
                              </span>
                            ) : null}
                          </div>
                        ))}
                    </div>
                  ))}
                </li>
              ) : null}
              </Fragment>
            ))}
          </ul>
        ) : (
          <p className="muted small">
            Paste a YouTube URL above — the worker downloads it and syncs it to
            Google Drive <code>02_Processing</code>.
          </p>
        )}
      </div>
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchHealth();
        if (!cancelled) {
          setHealth(data);
          setError(null);
          setUpdatedAt(Date.now());
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "unknown error");
        }
      }
    };
    void load();
    const id = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  const overall = health?.status ?? (error ? "error" : "checking");

  return (
    <div className="app">
      <header className="topbar">
        <Logo />
        <StatusPill status={overall} />
      </header>

      <main className="content">
        <section className="hero">
          <h1 className="hero-title">
            Turn long videos into short-form content.
          </h1>
          <p className="hero-sub muted">
            ClipForge finds the best moments, edits them into 9:16 shorts, and
            publishes them — automatically. Phase 10: Drop &amp; Forget is
            live.
          </p>
        </section>

        <section className="stats" aria-label="Pipeline overview">
          {STATS.map((s) => (
            <article key={s.label} className="stat">
              <span className="stat-value">{s.value}</span>
              <span className="stat-label muted">{s.label}</span>
            </article>
          ))}
        </section>

        <div className="grid">
          <HealthSection health={health} error={error} updatedAt={updatedAt} />
          <AutomationPanel />
          <VideosPanel />
          <DrivePanel />
          <YouTubePanel />
        </div>
      </main>

      <footer className="footer muted small">
        ClipForge {health ? `v${health.version}` : ""} — self-hosted, Orange Pi
        ready · Phase 10
      </footer>
    </div>
  );
}
