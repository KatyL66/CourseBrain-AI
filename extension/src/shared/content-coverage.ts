export const MAX_FAILED_TITLES = 20;

export function extractViewContentTopicId(url?: string | null): string | null {
  if (!url) return null;
  const match =
    url.match(/\/viewContent\/(\d+)/i) ||
    url.match(/\/le\/lessons\/\d+\/topics\/(\d+)/i) ||
    url.match(/\/content\/topics\/(\d+)/i);
  return match?.[1] ?? null;
}

export function isInCourseContentUrl(url: string, origin: string): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url, origin);
    if (parsed.origin !== new URL(origin).origin) return false;
    const path = parsed.pathname.toLowerCase();
    if (path.includes("/d2l/login") || /\/d2l\/home\/?$/.test(path)) return false;
    return (
      path.includes("/d2l/le/content/") ||
      path.includes("/d2l/le/lessons/") ||
      path.includes("/content/enforced/") ||
      path.includes("/d2l/common/") ||
      path.includes("/d2l/lp/files/")
    );
  } catch {
    return false;
  }
}

export function isDirectCourseFileUrl(url: string, origin: string): boolean {
  if (!isInCourseContentUrl(url, origin)) return false;
  const path = new URL(url, origin).pathname.toLowerCase();
  return !path.includes("/viewcontent/") && !path.includes("/le/lessons/");
}

export function payloadLooksLikePdf(bytes: Uint8Array): boolean {
  return (
    bytes.length >= 5 &&
    bytes[0] === 0x25 &&
    bytes[1] === 0x50 &&
    bytes[2] === 0x44 &&
    bytes[3] === 0x46
  );
}

export function recordFailedTitle(
  titles: string[],
  title: string,
  cap = MAX_FAILED_TITLES,
): string[] {
  if (!title || titles.includes(title) || titles.length >= cap) return titles;
  return [...titles, title];
}

export function formatNamedListMessage(
  prefix: string,
  titles: string[] | undefined,
  count?: number,
): string {
  const n = count ?? titles?.length ?? 0;
  if (!n) return "";
  const named = (titles ?? []).filter(Boolean);
  if (!named.length) return `，${prefix} ${n}`;
  const shown = named.slice(0, 5);
  const more = named.length > shown.length ? ` 等${n}个` : "";
  return `，${prefix} ${n}：${shown.join("、")}${more}`;
}

export function formatFailedFetchMessage(
  failedFetch: number,
  titles: string[] | undefined,
): string {
  return formatNamedListMessage("失败", titles, failedFetch);
}

export function formatIngestSkippedMessage(skipped: string[] | undefined): string {
  return formatNamedListMessage("未入库", skipped, skipped?.length);
}

export const MODULE_DESC_MIN_CHARS = 80;

export type ModuleDescriptionSource = {
  Description?: { Html?: string; Text?: string } | string | null;
  Title?: string;
};

export function moduleDescriptionExternalId(moduleId: number | string): string {
  return `module-desc:${moduleId}`;
}

export function moduleDescriptionViewUrl(
  origin: string,
  courseId: string,
  moduleId: number | string,
): string {
  return `${origin}/d2l/le/content/${courseId}/Home?itemIdentifier=D2L.LE.Content.ContentObject.ModuleCO-${moduleId}`;
}

export function extractModuleDescriptionHtml(module: ModuleDescriptionSource | null | undefined): string {
  const description = module?.Description;
  if (!description) return "";
  if (typeof description === "string") return description.trim();
  return (description.Html || description.Text || "").trim();
}

export function htmlToPlainText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function isIngestibleModuleDescription(htmlOrText: string): boolean {
  const text = htmlToPlainText(htmlOrText);
  return text.length >= MODULE_DESC_MIN_CHARS;
}

export interface TocTopic {
  TopicId?: number;
  Id?: number;
  Title?: string;
  Url?: string;
  TopicType?: number;
  TypeIdentifier?: string;
  IsHidden?: boolean;
}

export interface TocModule {
  ModuleId?: number;
  Id?: number;
  Title?: string;
  Topics?: TocTopic[];
  Modules?: TocModule[];
  IsHidden?: boolean;
}

export interface TableOfContents {
  Modules?: TocModule[];
}

export interface FlattenedTocTopic {
  topicId: string;
  title: string;
  modulePath: string;
  url?: string;
  topicType?: number;
  typeIdentifier?: string;
}

export function flattenContentToc(
  toc: TableOfContents | TocModule[] | null | undefined,
): FlattenedTocTopic[] {
  const modules = Array.isArray(toc) ? toc : toc?.Modules ?? [];
  const out: FlattenedTocTopic[] = [];

  const walk = (mods: TocModule[], prefix: string) => {
    for (const mod of mods) {
      if (mod.IsHidden) continue;
      const title = (mod.Title || "").trim() || "Module";
      const path = prefix ? `${prefix} > ${title}` : title;
      for (const topic of mod.Topics || []) {
        if (topic.IsHidden) continue;
        const id = topic.TopicId ?? topic.Id;
        if (id == null) continue;
        out.push({
          topicId: String(id),
          title: (topic.Title || "").trim() || `Topic ${id}`,
          modulePath: path,
          url: topic.Url,
          topicType: topic.TopicType,
          typeIdentifier: topic.TypeIdentifier,
        });
      }
      if (mod.Modules?.length) walk(mod.Modules, path);
    }
  };

  walk(modules, "");
  return out;
}
