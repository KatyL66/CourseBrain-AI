import { extractExternalIdFromUrl, type SavedCourse } from "./types";

export type PageCourseStatus = "synced" | "unsynced" | "no-course-page";

export interface ResolveCourseSelectionInput {
  pageExternalId: string | null;
  courses: SavedCourse[];
  storedActiveCourseId: string | null;
}

export interface CourseSelection {
  activeCourseId: string | null;
  pageStatus: PageCourseStatus;
}

export interface NextUiCourseSelectionInput {
  resolved: CourseSelection;
  pageExternalId: string | null;
  previousPageExternalId: string | null;
  previousPageStatus: PageCourseStatus;
  currentActiveCourseId: string | null;
}

export interface UiCourseSelection {
  activeCourseId: string | null;
  persist: boolean;
  clearChat: boolean;
}

export function pageExternalIdFromTabUrl(url: string | undefined | null): string | null {
  if (!url?.includes("brightspace.usc.edu")) return null;
  return extractExternalIdFromUrl(url);
}

export function resolveCourseSelection(input: ResolveCourseSelectionInput): CourseSelection {
  const { pageExternalId, courses, storedActiveCourseId } = input;

  if (pageExternalId) {
    const onPage = courses.find((c) => c.externalId === pageExternalId);
    if (onPage) {
      return { activeCourseId: onPage.courseId, pageStatus: "synced" };
    }
    return { activeCourseId: null, pageStatus: "unsynced" };
  }

  let activeCourseId = storedActiveCourseId;
  if (!activeCourseId && courses.length > 0) {
    activeCourseId = courses[0].courseId;
  }
  return { activeCourseId, pageStatus: "no-course-page" };
}

/**
 * Auto-switch only when Brightspace course context changes.
 * Re-applying the same page preserves an explicit manual course selection.
 */
export function nextUiCourseSelection(input: NextUiCourseSelectionInput): UiCourseSelection {
  const {
    resolved,
    pageExternalId,
    previousPageExternalId,
    previousPageStatus,
    currentActiveCourseId,
  } = input;

  const contextChanged =
    pageExternalId !== previousPageExternalId || previousPageStatus !== resolved.pageStatus;

  if (!contextChanged) {
    return {
      activeCourseId: currentActiveCourseId ?? resolved.activeCourseId,
      persist: false,
      clearChat: false,
    };
  }

  if (resolved.pageStatus === "unsynced") {
    return { activeCourseId: null, persist: false, clearChat: true };
  }

  return {
    activeCourseId: resolved.activeCourseId,
    persist: Boolean(resolved.activeCourseId),
    clearChat: resolved.activeCourseId !== currentActiveCourseId,
  };
}
