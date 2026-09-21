export const BRIGHTSPACE_API_VERSION = "1.82";

export interface SavedCourse {
  courseId: string;
  externalId: string;
  name: string;
  topicCount: number;
  chunkCount: number;
  syncedAt: string;
}

export interface CourseSummary {
  id: string;
  external_id: string;
  name: string;
  platform: string;
  topic_count: number;
  chunk_count: number;
  created_at: string;
}

export interface SourceMetadata {
  platform: string;
  course_id: string;
  course_code?: string;
  module?: string;
  topic_id: string;
  topic_title: string;
  url: string;
  file_type?: string;
  page?: number;
  anchor_text?: string;
}

export interface TopicPayload {
  external_id: string;
  module_name?: string;
  title: string;
  url: string;
  file_type?: string;
  topic_type?: number;
  content?: string;
  content_base64?: string;
}

export interface IngestBatchRequest {
  external_id: string;
  name: string;
  platform: string;
  topics: TopicPayload[];
  assignments?: AssignmentPayload[];
}

export interface AssignmentAttachmentPayload {
  filename: string;
  file_type?: string;
  content?: string;
  content_base64?: string;
}

export interface AssignmentPayload {
  object_id: string;
  name: string;
  canonical_url: string;
  due_at?: string | null;
  submission_type?: string;
  instructions?: string;
  attachments: AssignmentAttachmentPayload[];
}

export interface IngestBatchResponse {
  course_id: string;
  indexed_topics: number;
  total_chunks: number;
  skipped: string[];
  indexed_assignments?: number;
}

export interface Citation {
  rank?: number;
  score?: number;
  topic_title: string;
  module?: string;
  page?: number;
  url: string;
  excerpt: string;
}

export interface SourceReference {
  id: string;
  rank: number;
  title: string;
  module?: string;
  page?: number;
  url: string;
  content_type?: string;
  label: string;
  excerpt: string;
}

export interface ChatResponse {
  answer: string;
  references: SourceReference[];
  referenced: Citation[];
  retrieved: Citation[];
}

export interface SyncProgress {
  phase: "discover" | "fetch" | "upload" | "done" | "error";
  current: number;
  total: number;
  message: string;
}

export interface DiscoverySummary {
  modulesDiscovered: number;
  resourcesDiscovered: number;
  pdfs: number;
  htmlContent: number;
  linksSkipped: number;
  containersSkipped: number;
  navigationSkipped: number;
  duplicatesSkipped: number;
  indexed: number;
    failedFetch: number;
    failedTitles?: string[];
    assignmentsDiscovered: number;
  }

export interface IndexResult {
  external_id: string;
  name: string;
  topics: TopicPayload[];
  assignments?: AssignmentPayload[];
  summary?: DiscoverySummary;
}

function firstQueryOu(url: URL): string | null {
  for (const key of ["ou", "OU", "orgUnitId", "OrgUnitId"]) {
    const value = url.searchParams.get(key);
    if (value && /^\d{4,}$/.test(value)) return value;
  }
  return null;
}

export function extractExternalIdFromUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    const fromQuery = firstQueryOu(parsed);
    if (fromQuery) return fromQuery;
    const pathMatch = parsed.pathname.match(/\/(\d{4,})(?:\/|$)/);
    return pathMatch?.[1] ?? null;
  } catch {
    const match = url.match(/\/(\d{4,})(?:\/|$|\?)/);
    return match?.[1] ?? null;
  }
}

export function courseSummaryToSaved(c: CourseSummary): SavedCourse {
  return {
    courseId: c.id,
    externalId: c.external_id,
    name: c.name,
    topicCount: c.topic_count,
    chunkCount: c.chunk_count,
    syncedAt: c.created_at,
  };
}
