export interface ServiceStatus {
  status: string;
  latency_ms?: number | null;
}

export interface HealthResponse {
  status: string;
  version: string;
  services: Record<string, ServiceStatus>;
  timestamp: string;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health", {
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`health check failed (HTTP ${res.status})`);
  return (await res.json()) as HealthResponse;
}
