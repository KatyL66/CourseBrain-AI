import { ingestBatch } from "../shared/api-client";
import { formatFailedFetchMessage, formatIngestSkippedMessage } from "../shared/content-coverage";
import {
  buildReferenceOpenUrl,
  isDirectPdfUrl,
  usesPdfHashNavigation,
} from "../shared/reference-navigation";
import type { SavedCourse, SyncProgress } from "../shared/types";
import { extractExternalIdFromUrl } from "../shared/types";

const PENDING_KEY = "pendingHighlight";

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "SYNC_PROGRESS") {
    chrome.storage.local.set({ syncProgress: msg.payload as SyncProgress });
    return;
  }

  if (msg.type === "START_SYNC") {
    handleSync(typeof msg.tabId === "number" ? msg.tabId : undefined).then(sendResponse);
    return true;
  }

  if (msg.type === "OPEN_AND_HIGHLIGHT") {
    openAndHighlight(msg.url, msg.anchorText, msg.page).then(sendResponse);
    return true;
  }

  if (msg.type === "GET_PAGE_EXTERNAL_ID") {
    getBrightspaceTab()
      .then((tab) => {
        const externalId = tab.url ? extractExternalIdFromUrl(tab.url) : null;
        sendResponse({ externalId });
      })
      .catch(() => sendResponse({ externalId: null }));
    return true;
  }
});

async function upsertCourse(entry: SavedCourse) {
  const data = await chrome.storage.local.get(["courses"]);
  const courses = (data.courses as SavedCourse[] | undefined) ?? [];
  const idx = courses.findIndex(
    (c) => c.externalId === entry.externalId || c.courseId === entry.courseId,
  );
  if (idx >= 0) courses[idx] = entry;
  else courses.unshift(entry);

  await chrome.storage.local.set({
    courses,
    activeCourseId: entry.courseId,
    courseId: entry.courseId,
    courseName: entry.name,
    externalCourseId: entry.externalId,
  });
}

async function getBrightspaceTab(preferredTabId?: number): Promise<chrome.tabs.Tab> {
  if (preferredTabId != null) {
    try {
      const preferred = await chrome.tabs.get(preferredTabId);
      if (preferred?.id && preferred.url?.includes("brightspace.usc.edu")) {
        return preferred;
      }
    } catch {
      // tab closed — fall through
    }
  }

  const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (active?.id && active.url?.includes("brightspace.usc.edu")) {
    return active;
  }

  const tabs = await chrome.tabs.query({
    currentWindow: true,
    url: "*://brightspace.usc.edu/*",
  });
  if (tabs[0]?.id) return tabs[0];

  throw new Error("请先打开 Brightspace 课程页面");
}

async function sendRunIndex(tabId: number) {
  try {
    return await chrome.tabs.sendMessage(tabId, { type: "RUN_INDEX" });
  } catch {
    // Content script not loaded yet — inject then retry
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content/brightspace-indexer.js"],
    });
    return await chrome.tabs.sendMessage(tabId, { type: "RUN_INDEX" });
  }
}

async function handleSync(tabId?: number) {
  try {
    const tab = await getBrightspaceTab(tabId);
    const response = await sendRunIndex(tab.id!);
    if (!response?.ok) throw new Error(response?.error || "索引失败");

    await chrome.storage.local.set({
      syncProgress: {
        phase: "upload",
        current: 0,
        total: response.result.topics.length,
        message: "上传到 CourseBrain 后端...",
      } satisfies SyncProgress,
    });

    const ingestResult = await ingestBatch({
      external_id: response.result.external_id,
      name: response.result.name,
      platform: "brightspace",
      topics: response.result.topics,
      assignments: response.result.assignments ?? [],
    });

    await upsertCourse({
      courseId: ingestResult.course_id,
      externalId: response.result.external_id,
      name: response.result.name,
      topicCount: ingestResult.indexed_topics,
      chunkCount: ingestResult.total_chunks,
      syncedAt: new Date().toISOString(),
    });

    const discovery = response.result.summary;
    const coverageMsg = discovery
      ? `发现 ${discovery.resourcesDiscovered} 个资源（PDF ${discovery.pdfs}）` +
        `，跳过导航 ${discovery.navigationSkipped + discovery.containersSkipped}` +
        formatFailedFetchMessage(discovery.failedFetch, discovery.failedTitles) +
        formatIngestSkippedMessage(ingestResult.skipped)
      : "";

    const assignmentMsg =
      ingestResult.indexed_assignments && ingestResult.indexed_assignments > 0
        ? `，${ingestResult.indexed_assignments} 个作业`
        : "";

    await chrome.storage.local.set({
      syncProgress: {
        phase: "done",
        current: ingestResult.indexed_topics,
        total: ingestResult.indexed_topics,
        message:
          `完成：索引 ${ingestResult.indexed_topics} 个文件${assignmentMsg}，${ingestResult.total_chunks} 段可搜索` +
          (coverageMsg ? ` · ${coverageMsg}` : ""),
      } satisfies SyncProgress,
    });

    return { ok: true, result: ingestResult };
  } catch (e) {
    let message = e instanceof Error ? e.message : String(e);
    if (message.includes("Receiving end does not exist")) {
      message = "无法连接页面脚本。请刷新 Brightspace 页面后重试。";
    }
    await chrome.storage.local.set({
      syncProgress: { phase: "error", current: 0, total: 0, message } satisfies SyncProgress,
    });
    return { ok: false, error: message };
  }
}

async function openAndHighlight(url: string, anchorText?: string, page?: number) {
  const openUrl = buildReferenceOpenUrl(url, page);
  const pdfHashNav = usesPdfHashNavigation(url, page);

  await chrome.storage.session.set({
    [PENDING_KEY]: { url: openUrl, anchorText, page, ts: Date.now(), pdfHashNav },
  });

  const tab = await chrome.tabs.create({ url: openUrl });
  const tabId = tab.id!;

  if (pdfHashNav) {
    return { ok: true };
  }

  return new Promise((resolve) => {
    const listener = (updatedTabId: number, info: chrome.tabs.TabChangeInfo) => {
      if (updatedTabId !== tabId || info.status !== "complete") return;
      chrome.tabs.onUpdated.removeListener(listener);

      chrome.scripting
        .executeScript({ target: { tabId }, files: ["content/brightspace-highlighter.js"] })
        .then(() =>
          chrome.tabs.sendMessage(tabId, { type: "HIGHLIGHT", anchorText, page }),
        )
        .finally(() => resolve({ ok: true }));
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== "complete" || !tab.url) return;
  const data = await chrome.storage.session.get(PENDING_KEY);
  const pending = data[PENDING_KEY] as {
    url: string;
    anchorText?: string;
    page?: number;
    pdfHashNav?: boolean;
  } | undefined;
  if (!pending) return;

  const isSSO = tab.url.includes("shibboleth") || tab.url.includes("/login");
  if (isSSO) return;

  if (pending.pdfHashNav && pending.page && isDirectPdfUrl(tab.url.split("#")[0])) {
    if (!tab.url.includes(`#page=${pending.page}`)) {
      await chrome.tabs.update(tabId, {
        url: buildReferenceOpenUrl(tab.url.split("#")[0], pending.page),
      });
    }
    await chrome.storage.session.remove(PENDING_KEY);
    return;
  }

  if (tab.url.includes("brightspace.usc.edu") && !tab.url.includes("viewContent")) {
    if (pending.url.includes("viewContent")) {
      await chrome.tabs.update(tabId, { url: pending.url });
      return;
    }
  }

  if (tab.url.includes("viewContent") || tab.url.startsWith(pending.url.split("?")[0].split("#")[0])) {
    chrome.scripting
      .executeScript({ target: { tabId }, files: ["content/brightspace-highlighter.js"] })
      .then(() =>
        chrome.tabs.sendMessage(tabId, {
          type: "HIGHLIGHT",
          anchorText: pending.anchorText,
          page: pending.page,
        }),
      );
    await chrome.storage.session.remove(PENDING_KEY);
  }
});

export {};
