import type {
  ChatResponse,
  CourseSummary,
  IngestBatchRequest,
  IngestBatchResponse,
} from "./types";
import { API_BASE, API_KEY } from "./api-config";

function errorDetail(body: string, statusText: string): string {
  const raw = body.trim() || statusText;
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (parsed.detail != null) return JSON.stringify(parsed.detail);
  } catch {
    // not JSON — use the raw body
  }
  return raw;
}

function buildHeaders(init?: HeadersInit): Headers {
  const headers = new Headers(init);
  if (!headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (API_KEY) {
    headers.set("X-CourseBrain-Key", API_KEY);
  }
  return headers;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(options?.headers),
  });
  if (!res.ok) {
    const err = await res.text();
    const requestId = res.headers.get("X-Request-ID");
    const detail = errorDetail(err, res.statusText);
    throw new Error(requestId ? `${detail} [request_id=${requestId}]` : detail);
  }
  return res.json();
}

export async function ingestBatch(payload: IngestBatchRequest): Promise<IngestBatchResponse> {
  return request("/api/v1/ingest/batch", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function chat(courseId: string, message: string): Promise<ChatResponse> {
  return request("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({ course_id: courseId, message }),
  });
}

export async function listCourses(): Promise<CourseSummary[]> {
  const data = await request<{ courses: CourseSummary[] }>("/api/v1/courses");
  return data.courses;
}

export async function getCourseByExternal(externalId: string) {
  return request<CourseSummary>(`/api/v1/courses/by-external/${externalId}`);
}

export async function healthCheck(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    return res.ok;
  } catch {
    return false;
  }
}
