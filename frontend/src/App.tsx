import { useEffect, useState } from "react";
import { fetchHealth, type HealthResponse } from "./api";

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
    status === "ok"
      ? "ok"
      : status === "degraded" || status === "warning"
        ? "warn"
        : status === "error"
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

function ProjectsSection() {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Recent projects</h2>
        <span className="muted small">imports arrive in Phase 2</span>
      </div>
      <div className="empty">
        <p className="muted">No projects yet.</p>
        <p className="muted small">
          Drop a video into <code>ClipForge/01_Inbox</code> on Google Drive and
          it will appear here.
        </p>
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

  const overall =
    health?.status ?? (error ? "error" : "checking");

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
            publishes them — automatically. Phase 1 foundation is running.
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
          <ProjectsSection />
        </div>
      </main>

      <footer className="footer muted small">
        ClipForge {health ? `v${health.version}` : ""} — self-hosted, Orange Pi
        ready · Phase 1
      </footer>
    </div>
  );
}
