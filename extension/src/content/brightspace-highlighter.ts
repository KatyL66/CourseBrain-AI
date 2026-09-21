function highlightText(anchorText?: string) {
  if (!anchorText) return;
  const searchStr = anchorText.slice(0, 80).toLowerCase();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node: Text | null;

  while ((node = walker.nextNode() as Text | null)) {
    const content = node.textContent?.toLowerCase() || "";
    const idx = content.indexOf(searchStr);
    if (idx === -1) continue;

    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + Math.min(searchStr.length, node.textContent?.length || 0));
    const mark = document.createElement("mark");
    mark.className = "coursebrain-highlight";
    mark.style.cssText = "background:#FFE066;padding:2px 4px;border-radius:3px;";
    range.surroundContents(mark);
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
    break;
  }
}

function jumpToPdfPage(page?: number) {
  if (!page) return;
  const app = (window as unknown as { PDFViewerApplication?: { page: number } }).PDFViewerApplication;
  if (app) {
    app.page = page;
  } else if (location.hash !== `#page=${page}`) {
    location.hash = `page=${page}`;
  }
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "HIGHLIGHT") {
    jumpToPdfPage(msg.page);
    setTimeout(() => highlightText(msg.anchorText), 500);
  }
});
