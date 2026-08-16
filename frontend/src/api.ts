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

export interface DriveStatus {
  connected: boolean;
  email?: string | null;
  storage_used?: number | null;
  storage_limit?: number | null;
  error?: string | null;
}

export interface DriveFile {
  id: string;
  filename: string;
  mime_type?: string | null;
  size?: number | null;
  created_at?: string | null;
}

export interface DriveFilesResponse {
  folder: string;
  files: DriveFile[];
}

interface ApiErrorBody {
  error?: { code?: string; detail?: string };
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (body.error?.detail) return body.error.detail;
    if (body.error?.code) return body.error.code;
  } catch {
    /* non-JSON body */
  }
  return `HTTP ${res.status}`;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch("/api/health", { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`health check failed (HTTP ${res.status})`);
  return (await res.json()) as HealthResponse;
}

export interface AutomationStatus {
  auto_approve: boolean;
  auto_approve_threshold: number;
  youtube_auto_publish: boolean;
}

export async function fetchAutomationStatus(): Promise<AutomationStatus> {
  const res = await fetch("/api/automation/status");
  if (!res.ok) throw new Error(`automation status failed (${await readError(res)})`);
  return (await res.json()) as AutomationStatus;
}

export async function fetchDriveStatus(): Promise<DriveStatus> {
  const res = await fetch("/api/google-drive/status");
  if (!res.ok) throw new Error(`drive status failed (${await readError(res)})`);
  return (await res.json()) as DriveStatus;
}

export async function fetchDriveFiles(): Promise<DriveFilesResponse> {
  const res = await fetch("/api/google-drive/files");
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as DriveFilesResponse;
}

export async function connectDrive(): Promise<{ auth_url: string }> {
  const res = await fetch("/api/google-drive/connect", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { auth_url: string };
}

export interface VideoSummary {
  id: number;
  source_url: string;
  title: string | null;
  channel: string | null;
  duration: number | null;
  status: string;
  error_code?: string | null;
  download_progress?: number | null;
  created_at?: string | null;
}

export interface ImportResult {
  video_id: number;
  status: string;
  message?: string;
}

export async function importVideo(url: string): Promise<ImportResult> {
  const res = await fetch("/api/videos/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, upload_to_drive: true }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as ImportResult;
}

export async function fetchVideos(): Promise<VideoSummary[]> {
  const res = await fetch("/api/videos");
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as { videos: VideoSummary[] };
  return body.videos;
}

export async function transcribeVideo(
  videoId: number,
): Promise<{ status: string; message?: string }> {
  const res = await fetch(`/api/videos/${videoId}/transcribe`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { status: string; message?: string };
}

export interface Candidate {
  id: number;
  video_id: number;
  start_time: number;
  end_time: number;
  title: string;
  hook?: string | null;
  reason?: string | null;
  score: number;
  hook_score: number;
  content_score: number;
  context_score: number;
  emotion_score: number;
  standalone_score: number;
  retention_score: number;
  status: string;
}

export interface CandidatesResponse {
  video_id: number;
  candidates: Candidate[];
}

export async function analyzeVideo(
  videoId: number,
): Promise<{ status: string; message?: string }> {
  const res = await fetch(`/api/videos/${videoId}/analyze`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { status: string; message?: string };
}

export async function fetchCandidates(videoId: number): Promise<Candidate[]> {
  const res = await fetch(`/api/videos/${videoId}/candidates`);
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as CandidatesResponse;
  return body.candidates;
}

export async function setCandidateStatus(
  candidateId: number,
  action: "approve" | "reject",
): Promise<{ status: string }> {
  const res = await fetch(`/api/candidates/${candidateId}/${action}`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { status: string };
}

export interface RenderStatus {
  id: number;
  candidate_id: number;
  video_id: number;
  status: string;
  filesize?: number | null;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  quality_passed?: boolean | null;
  remote_path?: string | null;
  error_code?: string | null;
  created_at?: string | null;
}

export async function renderCandidate(
  candidateId: number,
): Promise<{ status: string; message?: string }> {
  const res = await fetch(`/api/candidates/${candidateId}/render`, { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { status: string; message?: string };
}

export async function fetchRenderStatus(
  candidateId: number,
): Promise<RenderStatus | null> {
  const res = await fetch(`/api/candidates/${candidateId}/render`);
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as {
    candidate_id: number;
    render: RenderStatus | null;
  };
  return body.render;
}

export function renderFileUrl(renderId: number): string {
  return `/api/renders/${renderId}/file`;
}

export interface YouTubeStatus {
  connected: boolean;
  channel_name?: string | null;
  error?: string | null;
}

export async function fetchYouTubeStatus(): Promise<YouTubeStatus> {
  const res = await fetch("/api/youtube/status");
  if (!res.ok) throw new Error(`youtube status failed (${await readError(res)})`);
  return (await res.json()) as YouTubeStatus;
}

export async function connectYouTube(): Promise<{ auth_url: string }> {
  const res = await fetch("/api/youtube/connect", { method: "POST" });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as { auth_url: string };
}

export interface PublishOptions {
  title?: string;
  description?: string;
  tags?: string;
  privacy?: "private" | "unlisted" | "public";
  scheduled_at?: string | null;
}

export interface Publication {
  id: number;
  render_id: number;
  video_id: number;
  youtube_video_id?: string | null;
  title: string;
  description?: string | null;
  tags?: string | null;
  privacy: string;
  scheduled_at?: string | null;
  status: string;
  error_code?: string | null;
  published_at?: string | null;
  created_at?: string | null;
}

export async function publishRender(
  renderId: number,
  options: PublishOptions = {},
): Promise<{ publication_id: number; status: string; message?: string }> {
  const res = await fetch(`/api/renders/${renderId}/publish`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as {
    publication_id: number;
    status: string;
    message?: string;
  };
}

export async function fetchPublications(
  videoId?: number,
): Promise<Publication[]> {
  const qs = videoId != null ? `?video_id=${videoId}` : "";
  const res = await fetch(`/api/publications${qs}`);
  if (!res.ok) throw new Error(await readError(res));
  const body = (await res.json()) as { publications: Publication[] };
  return body.publications;
}
