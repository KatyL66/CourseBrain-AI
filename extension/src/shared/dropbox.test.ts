import { describe, expect, it } from "vitest";
import { dropboxFolderUrl, dueAtFromFolder, isSearchableAttachment, submissionTypeLabel } from "./dropbox";

describe("dropbox helpers", () => {
  it("builds the student dropbox folder URL", () => {
    expect(dropboxFolderUrl("https://brightspace.usc.edu", "1001", "9001")).toBe(
      "https://brightspace.usc.edu/d2l/lms/dropbox/user/folder_submit_files.d2l?db=9001&ou=1001",
    );
  });

  it("uses DueDate and never Availability.EndDate", () => {
    expect(
      dueAtFromFolder({
        DueDate: "2026-09-16T06:59:00.000Z",
        Availability: { EndDate: "2023-12-21T07:59:00.000Z" },
      }),
    ).toBe("2026-09-16T06:59:00.000Z");
    expect(
      dueAtFromFolder({
        DueDate: null,
        Availability: { EndDate: "2023-12-21T07:59:00.000Z" },
      }),
    ).toBeNull();
  });

  it("maps submission type integers", () => {
    expect(submissionTypeLabel(0)).toBe("File");
    expect(submissionTypeLabel("File")).toBe("File");
  });

  it("does not treat spreadsheets as searchable assignment text", () => {
    expect(isSearchableAttachment("hw3b.pdf")).toBe(true);
    expect(isSearchableAttachment("hw2b_part2_data.xls")).toBe(false);
    expect(isSearchableAttachment("notes.xlsx")).toBe(false);
  });
});
