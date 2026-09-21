import { useCallback, useEffect, useRef, useState } from "react";
import { chat, healthCheck, listCourses } from "../shared/api-client";
import { isLocalApi } from "../shared/api-config";
import {
  nextUiCourseSelection,
  pageExternalIdFromTabUrl,
  resolveCourseSelection,
  type PageCourseStatus,
} from "../shared/course-selection";
import { CitationCard } from "./CitationCard";
import { CourseSwitcher } from "./CourseSwitcher";
import { AnswerWithSources } from "./AnswerWithSources";
import type { ChatResponse, SavedCourse, SourceReference, SyncProgress } from "../shared/types";
import { courseSummaryToSaved } from "../shared/types";

async function loadStoredCourses(): Promise<{
  courses: SavedCourse[];
  activeCourseId: string | null;
}> {
  return new Promise((resolve) => {
    chrome.storage.local.get(["courses", "activeCourseId", "courseId"], (data) => {
      let courses = (data.courses as SavedCourse[] | undefined) ?? [];
      let activeCourseId = (data.activeCourseId as string | undefined) ?? null;

      // Migrate legacy single-course storage
      if (courses.length === 0 && data.courseId) {
        courses = [{
          courseId: data.courseId as string,
          externalId: (data.externalCourseId as string) || "",
          name: (data.courseName as string) || "已同步课程",
          topicCount: 0,
          chunkCount: 0,
          syncedAt: new Date().toISOString(),
        }];
        activeCourseId = data.courseId as string;
      }

      resolve({ courses, activeCourseId });
    });
  });
}

async function getActiveBrightspaceTab(): Promise<chrome.tabs.Tab | undefined> {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.url?.includes("brightspace.usc.edu")) return tab;
  } catch {
    // fall through
  }
  return undefined;
}

function mergeCourses(local: SavedCourse[], remote: SavedCourse[]): SavedCourse[] {
  const map = new Map<string, SavedCourse>();
  for (const c of local) map.set(c.courseId, c);
  for (const c of remote) map.set(c.courseId, { ...map.get(c.courseId), ...c });
  return Array.from(map.values()).sort(
    (a, b) => new Date(b.syncedAt).getTime() - new Date(a.syncedAt).getTime(),
  );
}

export function App() {
  const [courses, setCourses] = useState<SavedCourse[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<string | null>(null);
  const [pageExternalId, setPageExternalId] = useState<string | null>(null);
  const [pageStatus, setPageStatus] = useState<PageCourseStatus>("no-course-page");
  const [syncProgress, setSyncProgress] = useState<SyncProgress | null>(null);
  const [apiOnline, setApiOnline] = useState(false);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatResult, setChatResult] = useState<ChatResponse | null>(null);
  const [showRetrieved, setShowRetrieved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeCourse = courses.find((c) => c.courseId === activeCourseId);
  const pageUnsynced = pageStatus === "unsynced";
  const canAsk = Boolean(activeCourseId);
  const askingOtherThanPage = pageUnsynced && Boolean(activeCourse);

  const coursesRef = useRef(courses);
  coursesRef.current = courses;
  const pageExternalIdRef = useRef(pageExternalId);
  pageExternalIdRef.current = pageExternalId;
  const pageStatusRef = useRef(pageStatus);
  pageStatusRef.current = pageStatus;
  const activeCourseIdRef = useRef(activeCourseId);
  activeCourseIdRef.current = activeCourseId;
  const pageTabIdRef = useRef<number | undefined>(undefined);
  const applyGenRef = useRef(0);

  const applyCourseSelection = useCallback(async (merged: SavedCourse[]) => {
    const gen = ++applyGenRef.current;
    const prevPageId = pageExternalIdRef.current;
    const prevStatus = pageStatusRef.current;

    const tab = await getActiveBrightspaceTab();
    const pageId = pageExternalIdFromTabUrl(tab?.url);
    if (gen !== applyGenRef.current) return;

    if (tab?.id != null && pageId) pageTabIdRef.current = tab.id;

    const stored = await loadStoredCourses();
    if (gen !== applyGenRef.current) return;

    const resolved = resolveCourseSelection({
      pageExternalId: pageId,
      courses: merged,
      storedActiveCourseId: stored.activeCourseId,
    });
    const next = nextUiCourseSelection({
      resolved,
      pageExternalId: pageId,
      previousPageExternalId: prevPageId,
      previousPageStatus: prevStatus,
      currentActiveCourseId: activeCourseIdRef.current,
    });

    setPageExternalId(pageId);
    pageExternalIdRef.current = pageId;
    setPageStatus(resolved.pageStatus);
    pageStatusRef.current = resolved.pageStatus;
    setActiveCourseId(next.activeCourseId);
    activeCourseIdRef.current = next.activeCourseId;
    if (next.clearChat) {
      setChatResult(null);
      setShowRetrieved(false);
    }
    if (next.persist && next.activeCourseId) {
      await chrome.storage.local.set({
        activeCourseId: next.activeCourseId,
        courseId: next.activeCourseId,
      });
    }
  }, []);

  const refreshCourses = useCallback(async () => {
    const stored = await loadStoredCourses();
    let merged = stored.courses;

    if (await healthCheck()) {
      try {
        const remote = (await listCourses()).map(courseSummaryToSaved);
        merged = mergeCourses(stored.courses, remote);
        await chrome.storage.local.set({ courses: merged });
      } catch {
        // use local only if API list fails
      }
    }

    setCourses(merged);
    await applyCourseSelection(merged);
  }, [applyCourseSelection]);

  useEffect(() => {
    healthCheck().then(setApiOnline);
    refreshCourses();

    chrome.storage.local.get(["syncProgress"], (data) => {
      if (data.syncProgress) setSyncProgress(data.syncProgress as SyncProgress);
    });

    const onChange = (
      changes: Record<string, chrome.storage.StorageChange>,
      area: string,
    ) => {
      if (area !== "local") return;
      if (changes.courses?.newValue) {
        const next = changes.courses.newValue as SavedCourse[];
        setCourses(next);
        void applyCourseSelection(next);
      }
      if (changes.syncProgress?.newValue) {
        setSyncProgress(changes.syncProgress.newValue as SyncProgress);
        if (changes.syncProgress.newValue.phase === "done") {
          refreshCourses();
        }
      }
    };
    chrome.storage.onChanged.addListener(onChange);
    return () => chrome.storage.onChanged.removeListener(onChange);
  }, [applyCourseSelection, refreshCourses]);

  useEffect(() => {
    const rerunIfCourseContextChanged = async (tabId?: number) => {
      if (tabId != null) {
        const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (active?.id !== tabId) return;
      }
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const nextId = pageExternalIdFromTabUrl(tab?.url);
      if (nextId === pageExternalIdRef.current) return;
      void applyCourseSelection(coursesRef.current);
    };

    const onActivated = () => {
      void rerunIfCourseContextChanged();
    };
    const onUpdated = (tabId: number, info: chrome.tabs.TabChangeInfo) => {
      if (!info.url && info.status !== "complete") return;
      void rerunIfCourseContextChanged(tabId);
    };

    chrome.tabs.onActivated.addListener(onActivated);
    chrome.tabs.onUpdated.addListener(onUpdated);
    return () => {
      chrome.tabs.onActivated.removeListener(onActivated);
      chrome.tabs.onUpdated.removeListener(onUpdated);
    };
  }, [applyCourseSelection]);

  const handleSelectCourse = useCallback(async (courseId: string) => {
    setActiveCourseId(courseId);
    activeCourseIdRef.current = courseId;
    setChatResult(null);
    setShowRetrieved(false);
    setError(null);
    await chrome.storage.local.set({ activeCourseId: courseId, courseId });
  }, []);

  const handleSync = useCallback(async () => {
    setError(null);
    setSyncProgress({ phase: "discover", current: 0, total: 0, message: "开始同步..." });
    try {
      const tab = await getActiveBrightspaceTab();
      const tabId = tab?.id ?? pageTabIdRef.current;
      const res = await chrome.runtime.sendMessage({ type: "START_SYNC", tabId });
      if (!res?.ok) setError(res?.error || "同步失败");
      else await refreshCourses();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [refreshCourses]);

  const handleAsk = useCallback(async () => {
    if (!activeCourseId || !query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await chat(activeCourseId, query.trim());
      setChatResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [activeCourseId, query]);

  const handleOpenSource = useCallback((ref: SourceReference) => {
    chrome.runtime.sendMessage({
      type: "OPEN_AND_HIGHLIGHT",
      url: ref.url,
      anchorText: ref.excerpt.slice(0, 80),
      page: ref.page,
    });
  }, []);

  return (
    <div className="app">
      <header className="header">
        <h1>CourseBrain</h1>
        <div className="header-status">
          <span className={`status ${apiOnline ? "online" : "offline"}`}>
            {apiOnline ? "API 在线" : "API 离线"}
          </span>
          {!isLocalApi() && <span className="status staging">Staging</span>}
        </div>
      </header>

      <section className="card">
        <CourseSwitcher
          courses={courses}
          activeCourseId={activeCourseId}
          pageExternalId={pageExternalId}
          onSelect={handleSelectCourse}
        />
      </section>

      <section className="card">
        <p className="course-label">
          {activeCourse
            ? askingOtherThanPage
              ? `提问：${activeCourse.name}（不是当前 Brightspace 页面）`
              : `提问：${activeCourse.name}`
            : pageUnsynced
              ? "当前课程尚未同步"
              : "请先同步或选择一门课"}
        </p>
        {pageUnsynced && (
          <div className="unsynced-banner">
            当前 Brightspace 课程尚未同步到 CourseBrain。请同步当前课程，或手动选择一门已同步课程提问。
          </div>
        )}
        <button className="btn primary" onClick={handleSync} disabled={!apiOnline}>
          同步当前 Brightspace 课程
        </button>
        {syncProgress && (
          <div className="progress">
            <p>{syncProgress.message}</p>
            {syncProgress.total > 0 && syncProgress.phase !== "done" && (
              <div className="bar">
                <div
                  className="fill"
                  style={{ width: `${(syncProgress.current / syncProgress.total) * 100}%` }}
                />
              </div>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <textarea
          className="input"
          rows={3}
          placeholder={
            canAsk ? "例如：group project 的要求是什么？" : "请先同步当前课程，或选择一门已同步课程"
          }
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={!canAsk}
        />
        <button
          className="btn"
          onClick={handleAsk}
          disabled={!canAsk || loading || !query.trim()}
        >
          {loading ? "搜索中..." : "提问"}
        </button>
      </section>

      {error && <div className="error">{error}</div>}

      {chatResult && (
        <section className="card answer">
          <h2>回答</h2>
          <AnswerWithSources
            answer={chatResult.answer}
            references={chatResult.references ?? []}
            onOpenSource={handleOpenSource}
          />

          {chatResult.referenced.length > 0 && (
            <>
              <h3>课程依据</h3>
              <p className="sources-hint">
                本回答引用的课程材料，点击可打开 Brightspace 原文。
              </p>
              {chatResult.referenced.map((c) => (
                <CitationCard
                  key={`ref-${c.rank ?? 0}-${c.url}-${c.page ?? "na"}`}
                  citation={c}
                  onOpen={(url, excerpt, page) =>
                    handleOpenSource({
                      id: `cit-${c.rank}`,
                      rank: c.rank ?? 0,
                      title: c.topic_title,
                      module: c.module,
                      page: c.page,
                      url,
                      label: c.module ?? c.topic_title,
                      excerpt,
                    })
                  }
                />
              ))}
            </>
          )}

          {chatResult.retrieved.length > 0 && (
            <div className="retrieved-section">
              <button
                type="button"
                className="retrieved-toggle"
                onClick={() => setShowRetrieved((v) => !v)}
              >
                {showRetrieved ? "隐藏" : "查看"}检索上下文（{chatResult.retrieved.length}）
              </button>
              {showRetrieved && (
                <div className="retrieved-panel">
                  <p className="sources-hint">
                    调试信息：发给模型的 Top {chatResult.retrieved.length} 检索片段（未必全部被引用）。
                  </p>
                  {chatResult.retrieved.map((c) => (
                    <CitationCard
                      key={`ret-${c.rank ?? 0}-${c.url}-${c.page ?? "na"}`}
                      citation={c}
                      onOpen={(url, excerpt, page) =>
                    handleOpenSource({
                      id: `cit-${c.rank}`,
                      rank: c.rank ?? 0,
                      title: c.topic_title,
                      module: c.module,
                      page: c.page,
                      url,
                      label: c.module ?? c.topic_title,
                      excerpt,
                    })
                  }
                      showScore
                    />
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      <footer className="footer">
        切换课程后提问会针对所选课程；在课程页打开会自动选中该课
      </footer>
    </div>
  );
}
