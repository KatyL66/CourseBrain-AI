import { describe, expect, it } from "vitest";
import { extractExternalIdFromUrl, type SavedCourse } from "./types";
import {
  nextUiCourseSelection,
  pageExternalIdFromTabUrl,
  resolveCourseSelection,
} from "./course-selection";

const num201: SavedCourse = {
  courseId: "uuid-num",
  externalId: "1003",
  name: "NUM-201",
  topicCount: 10,
  chunkCount: 100,
  syncedAt: "2026-09-01T00:00:00.000Z",
};

const cs101: SavedCourse = {
  courseId: "uuid-cs",
  externalId: "1001",
  name: "CS-101",
  topicCount: 8,
  chunkCount: 80,
  syncedAt: "2026-09-02T00:00:00.000Z",
};

const courses = [cs101, num201];

describe("resolveCourseSelection", () => {
  it("auto-selects the synced course matching the page OU", () => {
    const result = resolveCourseSelection({
      pageExternalId: "1003",
      courses,
      storedActiveCourseId: "uuid-cs",
    });
    expect(result).toEqual({ activeCourseId: "uuid-num", pageStatus: "synced" });
  });

  it("does not fall back to the previous course on an unsynced page OU", () => {
    const result = resolveCourseSelection({
      pageExternalId: "2001",
      courses,
      storedActiveCourseId: "uuid-num",
    });
    expect(result).toEqual({ activeCourseId: null, pageStatus: "unsynced" });
  });

  it("does not fall back to courses[0] on an unsynced page OU with no stored course", () => {
    const result = resolveCourseSelection({
      pageExternalId: "2001",
      courses,
      storedActiveCourseId: null,
    });
    expect(result).toEqual({ activeCourseId: null, pageStatus: "unsynced" });
  });

  it("keeps the stored course on Brightspace home / no course context", () => {
    const result = resolveCourseSelection({
      pageExternalId: null,
      courses,
      storedActiveCourseId: "uuid-num",
    });
    expect(result).toEqual({ activeCourseId: "uuid-num", pageStatus: "no-course-page" });
  });

  it("falls back to the first course on home when nothing is stored", () => {
    const result = resolveCourseSelection({
      pageExternalId: null,
      courses,
      storedActiveCourseId: null,
    });
    expect(result).toEqual({ activeCourseId: "uuid-cs", pageStatus: "no-course-page" });
  });

  it("returns null on home when there are no synced courses", () => {
    const result = resolveCourseSelection({
      pageExternalId: null,
      courses: [],
      storedActiveCourseId: null,
    });
    expect(result).toEqual({ activeCourseId: null, pageStatus: "no-course-page" });
  });

  it("overrides a different stored course when the page OU is synced", () => {
    const result = resolveCourseSelection({
      pageExternalId: "1001",
      courses,
      storedActiveCourseId: "uuid-num",
    });
    expect(result).toEqual({ activeCourseId: "uuid-cs", pageStatus: "synced" });
  });
});

describe("pageExternalIdFromTabUrl", () => {
  it("extracts the course OU from a content URL", () => {
    expect(
      pageExternalIdFromTabUrl(
        "https://brightspace.usc.edu/d2l/le/content/1003/viewContent/55001/View",
      ),
    ).toBe("1003");
  });

  it("extracts the course OU from /d2l/home/{ou}", () => {
    expect(pageExternalIdFromTabUrl("https://brightspace.usc.edu/d2l/home/1003")).toBe("1003");
  });

  it("returns null for Brightspace home with no OU", () => {
    expect(pageExternalIdFromTabUrl("https://brightspace.usc.edu/d2l/home")).toBeNull();
  });

  it("returns null for a non-Brightspace tab", () => {
    expect(pageExternalIdFromTabUrl("https://example.com/d2l/home/1003")).toBeNull();
  });
});

describe("extractExternalIdFromUrl", () => {
  it("reads the first path OU on a course content URL", () => {
    expect(
      extractExternalIdFromUrl(
        "https://brightspace.usc.edu/d2l/le/content/1003/viewContent/55001/View",
      ),
    ).toBe("1003");
  });

  it("reads ou from a Dropbox folders list URL", () => {
    expect(
      extractExternalIdFromUrl(
        "https://brightspace.usc.edu/d2l/lms/dropbox/user/folders_list.d2l?ou=1002",
      ),
    ).toBe("1002");
  });

  it("prefers ou over the dropbox folder db id", () => {
    expect(
      extractExternalIdFromUrl(
        "https://brightspace.usc.edu/d2l/lms/dropbox/user/folder_submit_files.d2l?db=9001&ou=1002",
      ),
    ).toBe("1002");
  });

  it("extracts ou from Assignments list pages for page course matching", () => {
    expect(
      pageExternalIdFromTabUrl(
        "https://brightspace.usc.edu/d2l/lms/dropbox/user/folders_list.d2l?ou=1002",
      ),
    ).toBe("1002");
  });

  it("returns null for /d2l/home", () => {
    expect(extractExternalIdFromUrl("https://brightspace.usc.edu/d2l/home")).toBeNull();
  });
});

describe("nextUiCourseSelection", () => {
  const syncedCs = { activeCourseId: "uuid-cs", pageStatus: "synced" as const };
  const syncedOther = { activeCourseId: "uuid-other", pageStatus: "synced" as const };
  const unsynced = { activeCourseId: null, pageStatus: "unsynced" as const };
  const homeStoredNum = { activeCourseId: "uuid-num", pageStatus: "no-course-page" as const };

  it("Case A: entering a synced course page auto-selects that course", () => {
    expect(
      nextUiCourseSelection({
        resolved: syncedCs,
        pageExternalId: "1001",
        previousPageExternalId: null,
        previousPageStatus: "no-course-page",
        currentActiveCourseId: "uuid-num",
      }),
    ).toEqual({ activeCourseId: "uuid-cs", persist: true, clearChat: true });
  });

  it("Case B: switching to another synced course page auto-selects the new course", () => {
    expect(
      nextUiCourseSelection({
        resolved: syncedOther,
        pageExternalId: "2001",
        previousPageExternalId: "1001",
        previousPageStatus: "synced",
        currentActiveCourseId: "uuid-cs",
      }),
    ).toEqual({ activeCourseId: "uuid-other", persist: true, clearChat: true });
  });

  it("Case C: entering an unsynced course page does not silent-fallback", () => {
    expect(
      nextUiCourseSelection({
        resolved: unsynced,
        pageExternalId: "1004",
        previousPageExternalId: "1001",
        previousPageStatus: "synced",
        currentActiveCourseId: "uuid-cs",
      }),
    ).toEqual({ activeCourseId: null, persist: false, clearChat: true });
  });

  it("Case D: staying on an unsynced page keeps an explicit manual selection", () => {
    expect(
      nextUiCourseSelection({
        resolved: unsynced,
        pageExternalId: "1004",
        previousPageExternalId: "1004",
        previousPageStatus: "unsynced",
        currentActiveCourseId: "uuid-cs",
      }),
    ).toEqual({ activeCourseId: "uuid-cs", persist: false, clearChat: false });
  });

  it("Case E: sync recovery auto-selects the newly synced course", () => {
    expect(
      nextUiCourseSelection({
        resolved: { activeCourseId: "uuid-sim", pageStatus: "synced" },
        pageExternalId: "1004",
        previousPageExternalId: "1004",
        previousPageStatus: "unsynced",
        currentActiveCourseId: "uuid-cs",
      }),
    ).toEqual({ activeCourseId: "uuid-sim", persist: true, clearChat: true });
  });

  it("Case F: entering Brightspace home restores the stored course", () => {
    expect(
      nextUiCourseSelection({
        resolved: homeStoredNum,
        pageExternalId: null,
        previousPageExternalId: "1004",
        previousPageStatus: "unsynced",
        currentActiveCourseId: null,
      }),
    ).toEqual({ activeCourseId: "uuid-num", persist: true, clearChat: true });
  });

  it("keeps a manual override while remaining on the same synced page", () => {
    expect(
      nextUiCourseSelection({
        resolved: syncedCs,
        pageExternalId: "1001",
        previousPageExternalId: "1001",
        previousPageStatus: "synced",
        currentActiveCourseId: "uuid-num",
      }),
    ).toEqual({ activeCourseId: "uuid-num", persist: false, clearChat: false });
  });
});
