import {
  extractViewContentTopicId,
  extractModuleDescriptionHtml,
  flattenContentToc,
  isDirectCourseFileUrl,
  isInCourseContentUrl,
  isIngestibleModuleDescription,
  moduleDescriptionExternalId,
  moduleDescriptionViewUrl,
  payloadLooksLikePdf,
  recordFailedTitle,
  type TableOfContents,
} from "../shared/content-coverage";
import {
  dropboxFolderUrl,
  dueAtFromFolder,
  isSearchableAttachment,
  richTextToHtml,
  submissionTypeLabel,
} from "../shared/dropbox";
import { extractExternalIdFromUrl } from "../shared/types";

const API_VER = "1.82";

const CONTENT_TYPE_MODULE = 0;
const CONTENT_TYPE_TOPIC = 1;
const TOPIC_TYPE_FILE = 1;
const TOPIC_TYPE_LINK = 3;

interface AssignmentAttachmentPayload {
  filename: string;
  file_type?: string;
  content?: string;
  content_base64?: string;
}

interface AssignmentPayload {
  object_id: string;
  name: string;
  canonical_url: string;
  due_at?: string | null;
  submission_type?: string;
  instructions?: string;
  attachments: AssignmentAttachmentPayload[];
}

interface DropboxFolder {
  Id: number;
  Name: string;
  CustomInstructions?: unknown;
  DueDate?: string | null;
  Availability?: { StartDate?: string | null; EndDate?: string | null } | null;
  IsHidden?: boolean;
  SubmissionType?: string | number;
  Attachments?: { FileId: number; FileName: string; Size?: number }[];
}

interface TopicPayload {
  external_id: string;
  module_name?: string;
  title: string;
  url: string;
  file_type?: string;
  topic_type?: number;
  content?: string;
  content_base64?: string;
}

interface SyncProgress {
  phase: string;
  current: number;
  total: number;
  message: string;
}

interface DiscoverySummary {
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
  failedTitles: string[];
  assignmentsDiscovered: number;
}

interface IndexResult {
  external_id: string;
  name: string;
  topics: TopicPayload[];
  assignments: AssignmentPayload[];
  summary: DiscoverySummary;
}

interface ContentObject {
  Id: number;
  Title: string;
  Type: number;
  TopicType?: number;
  Url?: string;
  ParentModuleId?: number;
  Description?: { Html?: string; Text?: string } | string;
}

interface ModuleDetails {
  ModuleId?: number;
  Id?: number;
  Title?: string;
  Description?: { Html?: string; Text?: string } | string;
}

function extractCourseId(): string | null {
  const fromUrl = extractExternalIdFromUrl(location.href);
  if (fromUrl) return fromUrl;
  const hidden = document.querySelector<HTMLInputElement>('input[name="ou"]');
  if (hidden?.value && /^\d{4,}$/.test(hidden.value)) return hidden.value;
  return null;
}

function absoluteUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${location.origin}${path.startsWith("/") ? "" : "/"}${path}`;
}

function topicViewUrl(courseId: string, topicId: string): string {
  return `${location.origin}/d2l/le/content/${courseId}/viewContent/${topicId}/View`;
}

function fileKindFromUrl(url?: string): "pdf" | "html" {
  const lower = (url || "").toLowerCase();
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  return "pdf";
}

function fileExt(filename: string): string {
  const match = filename.toLowerCase().match(/\.([a-z0-9]+)$/);
  return match?.[1] ?? "";
}

function isNavigationHtml(html: string): boolean {
  const markers = [
    "Table of Contents -",
    "d2l-navigation",
    "Notifications Account Settings",
    "Are You Still There?",
  ];
  let hits = 0;
  for (const m of markers) {
    if (html.includes(m)) hits++;
  }
  return hits >= 2;
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: "include" });
  if (!res.ok) throw new Error(`API ${path} failed: ${res.status}`);
  return res.json();
}

function logDiscovery(message: string): void {
  console.log(`[CourseBrain] ${message}`);
}

function moduleTitleFromPath(modulePath: string): string {
  const parts = modulePath.split(">").map((part) => part.trim()).filter(Boolean);
  return parts[parts.length - 1] || modulePath;
}

async function ingestModuleDescription(
  courseId: string,
  moduleId: number,
  modulePath: string,
  out: TopicPayload[],
  seenTopicIds: Set<string>,
  summary: DiscoverySummary,
  embedded?: ContentObject,
): Promise<void> {
  const topicId = moduleDescriptionExternalId(moduleId);
  if (seenTopicIds.has(topicId)) return;

  let html = extractModuleDescriptionHtml(embedded);
  if (!isIngestibleModuleDescription(html)) {
    try {
      const details = await apiGet<ModuleDetails>(
        `/d2l/api/le/${API_VER}/${courseId}/content/modules/${moduleId}`,
      );
      html = extractModuleDescriptionHtml(details);
    } catch (e) {
      logDiscovery(`  ${modulePath} [module description] fetch failed: ${String(e)}`);
      return;
    }
  }

  if (!isIngestibleModuleDescription(html)) {
    logDiscovery(`  ${modulePath} [module description] → SKIP empty`);
    return;
  }

  seenTopicIds.add(topicId);
  summary.resourcesDiscovered++;
  summary.htmlContent++;
  logDiscovery(`  ${modulePath} [module description] → INGEST`);
  out.push({
    external_id: topicId,
    module_name: modulePath,
    title: moduleTitleFromPath(modulePath),
    url: moduleDescriptionViewUrl(location.origin, courseId, moduleId),
    file_type: "html",
    content: html,
  });
}

async function discoverModuleStructure(
  courseId: string,
  moduleId: number,
  modulePath: string,
  out: TopicPayload[],
  seenTopicIds: Set<string>,
  summary: DiscoverySummary,
  embedded?: ContentObject,
): Promise<void> {
  summary.modulesDiscovered++;
  await ingestModuleDescription(
    courseId, moduleId, modulePath, out, seenTopicIds, summary, embedded,
  );

  let items: ContentObject[] = [];
  try {
    const structure = await apiGet<ContentObject[]>(
      `/d2l/api/le/${API_VER}/${courseId}/content/modules/${moduleId}/structure/`,
    );
    items = Array.isArray(structure) ? structure : [structure];
  } catch (e) {
    logDiscovery(`MODULE structure failed for ${modulePath}: ${String(e)}`);
    return;
  }

  logDiscovery(`MODULE: ${modulePath}`);

  for (const item of items) {
    if (item.Type === CONTENT_TYPE_MODULE) {
      summary.containersSkipped++;
      const childPath = `${modulePath} > ${item.Title}`;
      logDiscovery(`  ${item.Title} [module container] → recurse`);
      await discoverModuleStructure(
        courseId, item.Id, childPath, out, seenTopicIds, summary, item,
      );
      continue;
    }

    if (item.Type !== CONTENT_TYPE_TOPIC) {
      logDiscovery(`  ${item.Title} [type ${item.Type}] → SKIP`);
      continue;
    }

    enqueueContentTopic(courseId, item, modulePath, out, seenTopicIds, summary);
  }
}

function enqueueContentTopic(
  courseId: string,
  item: ContentObject,
  modulePath: string,
  out: TopicPayload[],
  seenTopicIds: Set<string>,
  summary: DiscoverySummary,
  source = "",
): void {
  const topicId = String(item.Id);
  const label = source ? `${source} ` : "";
  if (seenTopicIds.has(topicId)) {
    summary.duplicatesSkipped++;
    logDiscovery(`  ${item.Title} [duplicate id=${topicId}] → SKIP`);
    return;
  }

  if (item.TopicType === TOPIC_TYPE_LINK) {
    const url = item.Url ? absoluteUrl(item.Url) : topicViewUrl(courseId, topicId);
    if (!isInCourseContentUrl(url, location.origin)) {
      summary.linksSkipped++;
      logDiscovery(`  ${item.Title} [external link] ${url} → SKIP`);
      return;
    }
    const fileType = fileKindFromUrl(url);
    seenTopicIds.add(topicId);
    summary.resourcesDiscovered++;
    if (fileType === "pdf") summary.pdfs++;
    else summary.htmlContent++;
    logDiscovery(`  ${item.Title} [${label}in-course link] → INGEST`);
    out.push({
      external_id: topicId,
      module_name: modulePath,
      title: item.Title,
      url,
      topic_type: item.TopicType,
      file_type: fileType,
    });
    return;
  }

  if (item.TopicType === TOPIC_TYPE_FILE) {
    const fileType = fileKindFromUrl(item.Url);
    seenTopicIds.add(topicId);
    summary.resourcesDiscovered++;
    if (fileType === "pdf") summary.pdfs++;
    else summary.htmlContent++;
    logDiscovery(`  ${item.Title} [${label}${fileType.toUpperCase()}] → INGEST`);
    out.push({
      external_id: topicId,
      module_name: modulePath,
      title: item.Title,
      url: item.Url ? absoluteUrl(item.Url) : topicViewUrl(courseId, topicId),
      topic_type: item.TopicType,
      file_type: fileType,
    });
    return;
  }

  seenTopicIds.add(topicId);
  summary.resourcesDiscovered++;
  summary.htmlContent++;
  logDiscovery(`  ${item.Title} [${label}html topic type=${item.TopicType ?? "?"}] → INGEST`);
  out.push({
    external_id: topicId,
    module_name: modulePath,
    title: item.Title,
    url: item.Url ? absoluteUrl(item.Url) : topicViewUrl(courseId, topicId),
    topic_type: item.TopicType,
    file_type: "html",
  });
}

async function discoverFromToc(
  courseId: string,
  out: TopicPayload[],
  seenTopicIds: Set<string>,
  summary: DiscoverySummary,
): Promise<void> {
  let toc: TableOfContents;
  try {
    toc = await apiGet<TableOfContents>(
      `/d2l/api/le/${API_VER}/${courseId}/content/toc?ignoreDates=true`,
    );
  } catch (e) {
    logDiscovery(`TOC fetch failed: ${String(e)}`);
    return;
  }

  const listed = flattenContentToc(toc);
  logDiscovery(`TOC listed ${listed.length} student-visible topics`);
  let added = 0;
  for (const item of listed) {
    if (seenTopicIds.has(item.topicId)) continue;
    enqueueContentTopic(
      courseId,
      {
        Id: Number(item.topicId),
        Title: item.title,
        Type: CONTENT_TYPE_TOPIC,
        TopicType: item.topicType,
        Url: item.url,
      },
      item.modulePath,
      out,
      seenTopicIds,
      summary,
      "toc",
    );
    if (seenTopicIds.has(item.topicId)) added++;
  }
  logDiscovery(`TOC added ${added} topics missed by module walk`);
}

function topicFileApiPath(courseId: string, topicId: string): string {
  return `/d2l/api/le/${API_VER}/${courseId}/content/topics/${topicId}/file`;
}

function candidateFetchUrls(courseId: string, topic: TopicPayload): string[] {
  const urls: string[] = [];
  const add = (url?: string | null) => {
    if (!url || urls.includes(url)) return;
    urls.push(url);
  };
  add(topicFileApiPath(courseId, topic.external_id));
  const linkedId = extractViewContentTopicId(topic.url);
  if (linkedId && linkedId !== topic.external_id) {
    add(topicFileApiPath(courseId, linkedId));
  }
  if (topic.url && isDirectCourseFileUrl(topic.url, location.origin)) {
    add(topic.url);
  }
  return urls;
}

function recordFailedFetch(summary: DiscoverySummary, title: string): void {
  summary.failedFetch++;
  summary.failedTitles = recordFailedTitle(summary.failedTitles, title);
}

async function materializeFetchedResponse(
  res: Response,
  topic: TopicPayload,
): Promise<"nav" | TopicPayload | null> {
  const buffer = await res.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  if (payloadLooksLikePdf(bytes)) {
    topic.content_base64 = bytesToBase64(buffer);
    topic.file_type = "pdf";
    return topic;
  }

  const text = new TextDecoder("utf-8").decode(bytes);
  const contentType = (res.headers.get("content-type") || "").toLowerCase();
  const looksHtml = contentType.includes("html") || text.trimStart().startsWith("<");
  if (looksHtml) {
    if (isNavigationHtml(text)) return "nav";
    topic.content = text;
    topic.file_type = "html";
    return topic;
  }

  topic.content_base64 = bytesToBase64(buffer);
  topic.file_type = "pdf";
  return topic;
}

async function fetchTopicContent(
  courseId: string,
  topic: TopicPayload,
  summary: DiscoverySummary,
  onProgress?: (msg: string) => void,
): Promise<TopicPayload | null> {
  onProgress?.(`拉取: ${topic.title}`);
  if (topic.content || topic.content_base64) {
    return topic;
  }

  const urls = candidateFetchUrls(courseId, topic);
  let sawNavigation = false;

  for (const url of urls) {
    try {
      const res = await fetch(url, { credentials: "include" });
      if (!res.ok) {
        logDiscovery(`  ${topic.title} [${url}] → ${res.status}, retry`);
        continue;
      }
      const filled = await materializeFetchedResponse(res, topic);
      if (filled === "nav") {
        sawNavigation = true;
        logDiscovery(`  ${topic.title} [${url}] [navigation HTML] → retry`);
        continue;
      }
      if (filled?.content || filled?.content_base64) return filled;
    } catch (e) {
      logDiscovery(`  ${topic.title} [${url}] error: ${String(e)}`);
    }
  }

  if (sawNavigation) {
    summary.navigationSkipped++;
    logDiscovery(`  ${topic.title} [navigation HTML] → SKIP after fetch`);
    return null;
  }

  recordFailedFetch(summary, topic.title);
  logDiscovery(`  ${topic.title} [unsupported or fetch failed] → SKIP`);
  return null;
}

function bytesToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

async function fetchDropboxFolders(courseId: string): Promise<DropboxFolder[]> {
  const res = await fetch(`/d2l/api/le/${API_VER}/${courseId}/dropbox/folders/`, {
    credentials: "include",
  });
  if (res.status === 403 || res.status === 404) {
    logDiscovery(`Assignments API ${res.status} — skipping dropbox`);
    return [];
  }
  if (!res.ok) throw new Error(`Dropbox folders failed: ${res.status}`);
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

async function fetchAssignmentAttachment(
  courseId: string,
  folderId: number,
  fileId: number,
  filename: string,
): Promise<AssignmentAttachmentPayload | null> {
  const res = await fetch(
    `/d2l/api/le/${API_VER}/${courseId}/dropbox/folders/${folderId}/attachments/${fileId}`,
    { credentials: "include" },
  );
  if (!res.ok) return null;
  const contentType = res.headers.get("content-type") || "";
  const lower = filename.toLowerCase();
  const asHtml =
    contentType.includes("html") || lower.endsWith(".html") || lower.endsWith(".htm");
  if (asHtml) {
    return { filename, file_type: "html", content: await res.text() };
  }
  return {
    filename,
    file_type: "pdf",
    content_base64: bytesToBase64(await res.arrayBuffer()),
  };
}

async function ingestDropboxAssignments(
  courseId: string,
  summary: DiscoverySummary,
  onProgress?: (msg: string) => void,
): Promise<AssignmentPayload[]> {
  let folders: DropboxFolder[] = [];
  try {
    folders = await fetchDropboxFolders(courseId);
  } catch (e) {
    logDiscovery(`Assignments fetch failed: ${String(e)}`);
    return [];
  }

  const out: AssignmentPayload[] = [];
  for (const folder of folders) {
    if (folder.IsHidden) continue;
    summary.assignmentsDiscovered++;
    onProgress?.(`作业: ${folder.Name}`);
    const attachments: AssignmentAttachmentPayload[] = [];
    for (const file of folder.Attachments || []) {
      if (!isSearchableAttachment(file.FileName)) {
        attachments.push({ filename: file.FileName, file_type: fileExt(file.FileName) });
        continue;
      }
      try {
        const att = await fetchAssignmentAttachment(
          courseId,
          folder.Id,
          file.FileId,
          file.FileName,
        );
        if (att) attachments.push(att);
        else attachments.push({ filename: file.FileName, file_type: fileExt(file.FileName) });
      } catch {
        recordFailedFetch(summary, file.FileName || folder.Name);
        attachments.push({ filename: file.FileName, file_type: fileExt(file.FileName) });
      }
    }
    out.push({
      object_id: String(folder.Id),
      name: folder.Name,
      canonical_url: dropboxFolderUrl(location.origin, courseId, String(folder.Id)),
      due_at: dueAtFromFolder(folder),
      submission_type: submissionTypeLabel(folder.SubmissionType),
      instructions: richTextToHtml(folder.CustomInstructions) || undefined,
      attachments,
    });
  }
  logDiscovery(`Assignments discovered: ${summary.assignmentsDiscovered}`);
  return out;
}

async function runBrightspaceIndex(
  onProgress: (p: SyncProgress) => void,
): Promise<IndexResult> {
  const courseId = extractCourseId();
  if (!courseId) {
    throw new Error("无法识别当前课程，请打开一门 Brightspace 课程后再同步");
  }

  onProgress({ phase: "discover", current: 0, total: 0, message: "获取课程目录..." });

  const rootModules = await apiGet<ContentObject[]>(
    `/d2l/api/le/${API_VER}/${courseId}/content/root/`,
  );

  const courseName =
    document.querySelector(".d2l-navigation-s-title")?.textContent?.trim() ||
    document.title ||
    `Course ${courseId}`;

  const topics: TopicPayload[] = [];
  const seenTopicIds = new Set<string>();
  const summary: DiscoverySummary = {
    modulesDiscovered: 0,
    resourcesDiscovered: 0,
    pdfs: 0,
    htmlContent: 0,
    linksSkipped: 0,
    containersSkipped: 0,
    navigationSkipped: 0,
    duplicatesSkipped: 0,
    indexed: 0,
    failedFetch: 0,
    failedTitles: [],
    assignmentsDiscovered: 0,
  };

  logDiscovery("=== Discovery start ===");

  for (const item of rootModules) {
    if (item.Type === CONTENT_TYPE_TOPIC) {
      enqueueContentTopic(courseId, item, item.Title || "Root", topics, seenTopicIds, summary, "root");
      continue;
    }
    await discoverModuleStructure(
      courseId, item.Id, item.Title, topics, seenTopicIds, summary, item,
    );
  }
  await discoverFromToc(courseId, topics, seenTopicIds, summary);

  logDiscovery(
    `Discovered ${summary.resourcesDiscovered} resources ` +
      `(PDF ${summary.pdfs}, HTML ${summary.htmlContent}, ` +
      `containers skipped ${summary.containersSkipped}, links skipped ${summary.linksSkipped})`,
  );

  onProgress({
    phase: "fetch",
    current: 0,
    total: topics.length,
    message: `发现 ${topics.length} 个学习资源，开始拉取...`,
  });

  const enriched: TopicPayload[] = [];
  for (let i = 0; i < topics.length; i++) {
    const topic = topics[i];
    try {
      const filled = await fetchTopicContent(courseId, { ...topic }, summary, (msg) =>
        onProgress({
          phase: "fetch",
          current: i + 1,
          total: topics.length,
          message: msg,
        }),
      );
      if (filled?.content || filled?.content_base64) {
        enriched.push(filled);
        summary.indexed++;
      }
    } catch (e) {
      recordFailedFetch(summary, topic.title);
      console.warn("[CourseBrain] skip topic:", topic.title, e);
    }
    onProgress({
      phase: "fetch",
      current: i + 1,
      total: topics.length,
      message: `已拉取 ${i + 1}/${topics.length}`,
    });
  }

  onProgress({
    phase: "fetch",
    current: topics.length,
    total: topics.length,
    message: "获取 Brightspace Assignments...",
  });
  const assignments = await ingestDropboxAssignments(courseId, summary, (msg) =>
    onProgress({
      phase: "fetch",
      current: topics.length,
      total: topics.length,
      message: msg,
    }),
  );

  logDiscovery("=== Discovery summary ===");
  logDiscovery(`Resources discovered: ${summary.resourcesDiscovered}`);
  logDiscovery(`Successfully fetched: ${summary.indexed}`);
  logDiscovery(`Assignments: ${summary.assignmentsDiscovered}`);
  logDiscovery(`PDF: ${summary.pdfs}`);
  logDiscovery(`HTML content: ${summary.htmlContent}`);
  logDiscovery(`Containers skipped: ${summary.containersSkipped}`);
  logDiscovery(`Navigation skipped: ${summary.navigationSkipped}`);
  logDiscovery(`Links skipped: ${summary.linksSkipped}`);
  logDiscovery(`Duplicates skipped: ${summary.duplicatesSkipped}`);
  logDiscovery(`Failed fetch: ${summary.failedFetch}`);
  if (summary.failedTitles.length) {
    logDiscovery(`Failed titles: ${summary.failedTitles.join(", ")}`);
  }

  return {
    external_id: courseId,
    name: courseName,
    topics: enriched,
    assignments,
    summary,
  };
}

// Listen for index requests from background (guard against double-inject)
if (!(globalThis as unknown as { __courseBrainIndexer?: boolean }).__courseBrainIndexer) {
  (globalThis as unknown as { __courseBrainIndexer?: boolean }).__courseBrainIndexer = true;

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === "RUN_INDEX") {
      runBrightspaceIndex((progress) => {
        chrome.runtime.sendMessage({ type: "SYNC_PROGRESS", payload: progress }).catch(() => {});
      })
        .then((result) => sendResponse({ ok: true, result }))
        .catch((err) => sendResponse({ ok: false, error: String(err) }));
      return true;
    }
  });
}
