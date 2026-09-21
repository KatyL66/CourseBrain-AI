/** Build Brightspace reference open URLs (PDF page jump via Chrome native viewer). */

export function isDirectPdfUrl(url: string): boolean {
  const lower = url.toLowerCase();
  if (lower.includes("/d2l/api/") && lower.includes("/file")) return false;
  if (lower.includes("viewcontent")) return false;
  return lower.includes(".pdf") || lower.includes("/content/enforced/");
}

export function buildReferenceOpenUrl(url: string, page?: number): string {
  if (!page || !isDirectPdfUrl(url)) return url;
  const base = url.split("#")[0];
  return `${base}#page=${page}`;
}

export function usesPdfHashNavigation(url: string, page?: number): boolean {
  if (!page || !isDirectPdfUrl(url)) return false;
  return buildReferenceOpenUrl(url, page).includes("#page=");
}
