import { describe, expect, it } from "vitest";
import {
  extractModuleDescriptionHtml,
  extractViewContentTopicId,
  flattenContentToc,
  formatFailedFetchMessage,
  formatIngestSkippedMessage,
  isDirectCourseFileUrl,
  isInCourseContentUrl,
  isIngestibleModuleDescription,
  moduleDescriptionExternalId,
  moduleDescriptionViewUrl,
  payloadLooksLikePdf,
  recordFailedTitle,
} from "./content-coverage";

const ORIGIN = "https://brightspace.usc.edu";

describe("in-course content URLs", () => {
  it("accepts Overview PDF under /content/enforced/", () => {
    const url = `${ORIGIN}/content/enforced/1001-NUM_201/Overview.pdf`;
    expect(isInCourseContentUrl(url, ORIGIN)).toBe(true);
    expect(isDirectCourseFileUrl(url, ORIGIN)).toBe(true);
  });

  it("accepts viewContent links but does not treat them as direct files", () => {
    const url = `${ORIGIN}/d2l/le/content/1001/viewContent/55001/View`;
    expect(isInCourseContentUrl(url, ORIGIN)).toBe(true);
    expect(isDirectCourseFileUrl(url, ORIGIN)).toBe(false);
    expect(extractViewContentTopicId(url)).toBe("55001");
  });

  it("rejects YouTube and other off-course links", () => {
    expect(isInCourseContentUrl("https://www.youtube.com/watch?v=abc", ORIGIN)).toBe(false);
    expect(isInCourseContentUrl("/d2l/home/1001", ORIGIN)).toBe(false);
  });

  it("treats Brightspace quickLink and Lessons URLs as in-course", () => {
    expect(
      isInCourseContentUrl(
        `${ORIGIN}/d2l/common/dialogs/quickLink/quickLink.d2l?ou=1002&type=content&rcode=abc`,
        ORIGIN,
      ),
    ).toBe(true);
    expect(isInCourseContentUrl(`${ORIGIN}/d2l/le/lessons/1002/topics/77001`, ORIGIN)).toBe(true);
    expect(extractViewContentTopicId(`${ORIGIN}/d2l/le/lessons/1002/topics/77001`)).toBe("77001");
  });
});

describe("failed fetch summary", () => {
  it("names Overview in the sync message", () => {
    expect(formatFailedFetchMessage(2, ["Overview", "Course Schedule"])).toBe(
      "，失败 2：Overview、Course Schedule",
    );
  });

  it("caps named titles and records uniquely", () => {
    const titles = recordFailedTitle(["Overview"], "Overview");
    expect(titles).toEqual(["Overview"]);
    expect(recordFailedTitle(["Overview"], "Grading")).toEqual(["Overview", "Grading"]);
  });
});

describe("module description ingest", () => {
  it("extracts Brightspace RichText HTML", () => {
    const html = extractModuleDescriptionHtml({
      Description: {
        Html:
          "<h2>Course information</h2><h3>Grading</h3>" +
          "<p>Homework: 80 points of the total course grade. " +
          "Project: 150 points. Midterm and final exams: 170 points.</p>",
        Text: "Course information Grading Homework: 80 points of the total course grade.",
      },
    });
    expect(html).toContain("Homework: 80 points");
    expect(isIngestibleModuleDescription(html)).toBe(true);
  });

  it("skips empty welcome stubs", () => {
    expect(isIngestibleModuleDescription("<p>Hi</p>")).toBe(false);
  });

  it("builds a stable module-description topic id and Home URL", () => {
    expect(moduleDescriptionExternalId(77001)).toBe("module-desc:77001");
    expect(moduleDescriptionViewUrl(ORIGIN, "1002", 77001)).toContain(
      "ModuleCO-77001",
    );
  });
});

describe("student-visible TOC", () => {
  it("flattens Overview PDF topics that module-structure walk can miss", () => {
    const topics = flattenContentToc({
      Modules: [
        {
          Title: "Overview",
          Topics: [
            {
              TopicId: 77001,
              Title: "Overview",
              Url: "/content/enforced/1002-SIM_210/Overview.pdf",
              TopicType: 1,
            },
          ],
        },
        {
          Title: "Project",
          Topics: [{ TopicId: 99, Title: "Project Description", TopicType: 1 }],
        },
      ],
    });
    expect(topics.map((t) => t.title)).toEqual(["Overview", "Project Description"]);
    expect(topics[0].modulePath).toBe("Overview");
  });

  it("detects PDF magic bytes even when Content-Type is wrong", () => {
    const bytes = new TextEncoder().encode("%PDF-1.7\n...");
    expect(payloadLooksLikePdf(bytes)).toBe(true);
    expect(payloadLooksLikePdf(new TextEncoder().encode("<html>"))).toBe(false);
  });

  it("names backend-skipped files in the sync message", () => {
    expect(formatIngestSkippedMessage(["Overview", "Course Schedule"])).toBe(
      "，未入库 2：Overview、Course Schedule",
    );
  });
});
