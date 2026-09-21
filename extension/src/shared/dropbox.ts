/** Brightspace Dropbox (Assignments) helpers. DueDate only — never Availability. */

const SEARCHABLE_ATTACHMENT_EXT = [".pdf", ".html", ".htm", ".txt"] as const;

export function isSearchableAttachment(filename: string): boolean {
  const lower = filename.toLowerCase();
  return SEARCHABLE_ATTACHMENT_EXT.some((ext) => lower.endsWith(ext));
}

export function dropboxFolderUrl(origin: string, orgUnitId: string, folderId: string): string {
  const base = origin.replace(/\/$/, "");
  return `${base}/d2l/lms/dropbox/user/folder_submit_files.d2l?db=${encodeURIComponent(folderId)}&ou=${encodeURIComponent(orgUnitId)}`;
}

export function dueAtFromFolder(folder: {
  DueDate?: string | null;
  Availability?: { StartDate?: string | null; EndDate?: string | null } | null;
}): string | null {
  return folder.DueDate || null;
}

export function submissionTypeLabel(value: unknown): string | undefined {
  if (value == null || value === "") return undefined;
  const map: Record<string, string> = {
    "0": "File",
    "1": "Text",
    "2": "OnPaper",
    "3": "Observed",
    "4": "File or Text",
    File: "File",
    Text: "Text",
    OnPaper: "OnPaper",
    Observed: "Observed",
  };
  const key = String(value);
  return map[key] ?? key;
}

export function richTextToHtml(value: unknown): string {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const rec = value as { Html?: string; Text?: string };
    return rec.Html || rec.Text || "";
  }
  return "";
}
