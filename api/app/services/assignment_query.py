"""Named Brightspace assignment lookup and question-aspect classification."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from uuid import UUID
from zoneinfo import ZoneInfo

from app.db.object_store import AssignmentObject, assignments_store_exists, load_assignments
from app.models.schemas import Citation, SourceReference
from app.services.identifier_match import CourseIdentifier, extract_identifiers, identifiers_match

_STUDENT_TZ = ZoneInfo("America/Los_Angeles")

_DUE = re.compile(
    r"(?<![a-zA-Z])due(?![a-zA-Z])|deadline|截止|什么时候|啥时候|何时交|哪天交|今晚截止|when is\b",
    re.I,
)
_WHERE = re.compile(
    r"where (do i )?submit|where to submit|submission location|"
    r"在哪(里)?(提交|交)|交到哪|提交(在|到)?哪",
    re.I,
)
_OPEN = re.compile(r"^\s*open\b|\bopen hw|\bopen homework|打开", re.I)


class AssignmentAspect(str, Enum):
    DUE = "due"
    SUBMIT = "submit"
    OPEN = "open"
    INSTRUCTIONS = "instructions"


class AssignmentLookupStatus(str, Enum):
    FOUND = "found"
    MISSING_OBJECT = "missing_object"
    SOURCE_UNSYNCED = "source_unsynced"
    NOT_NAMED = "not_named"


def assignment_identifier_key(name: str) -> str | None:
    """Normalize dropbox title to hw:N when possible (assignment N → hw:N)."""
    ids = extract_identifiers(name)
    for kind in ("hw", "assignment", "lab", "project", "quiz"):
        for ident in ids:
            if ident.kind == kind and ident.number is not None:
                if kind == "assignment":
                    return f"hw:{ident.number}"
                return ident.key
    return None


def classify_assignment_aspect(question: str) -> AssignmentAspect:
    if _DUE.search(question):
        return AssignmentAspect.DUE
    if _WHERE.search(question):
        return AssignmentAspect.SUBMIT
    if _OPEN.search(question):
        return AssignmentAspect.OPEN
    return AssignmentAspect.INSTRUCTIONS


def _named_homework_ids(identifiers: list[CourseIdentifier]) -> list[CourseIdentifier]:
    return [
        ident
        for ident in identifiers
        if ident.number is not None and ident.kind in {"hw", "assignment", "lab", "project", "quiz"}
    ]


def resolve_named_assignment(
    course_id: UUID,
    identifiers: list[CourseIdentifier],
) -> AssignmentObject | None:
    """Return the unique assignment object matching a named HW/lab/quiz in the query."""
    wanted = _named_homework_ids(identifiers)
    if not wanted:
        return None

    assignments = load_assignments(course_id)
    matches: list[AssignmentObject] = []
    seen: set[str] = set()
    for obj in assignments:
        obj_ids = extract_identifiers(obj.name)
        if obj.identifier:
            kind, _, number = obj.identifier.partition(":")
            if number.isdigit():
                obj_ids = obj_ids + [CourseIdentifier(kind=kind, number=int(number))]
        if any(
            identifiers_match(query_id, obj_id)
            for query_id in wanted
            for obj_id in obj_ids
        ):
            if obj.object_id not in seen:
                seen.add(obj.object_id)
                matches.append(obj)

    if len(matches) == 1:
        return matches[0]
    return None


def lookup_named_assignment(
    course_id: UUID,
    identifiers: list[CourseIdentifier],
) -> tuple[AssignmentLookupStatus, AssignmentObject | None]:
    """Assignment-first lookup. MISSING_OBJECT means Assignments synced but this HW is not there."""
    if not _named_homework_ids(identifiers):
        return AssignmentLookupStatus.NOT_NAMED, None
    if not assignments_store_exists(course_id):
        return AssignmentLookupStatus.SOURCE_UNSYNCED, None
    obj = resolve_named_assignment(course_id, identifiers)
    if obj:
        return AssignmentLookupStatus.FOUND, obj
    return AssignmentLookupStatus.MISSING_OBJECT, None


def named_assignment_content_fallback_note(
    aspect: AssignmentAspect,
    status: AssignmentLookupStatus,
) -> str:
    """Prompt note when a named HW has no Assignment object. Content may still answer."""
    if status == AssignmentLookupStatus.SOURCE_UNSYNCED:
        availability = (
            "Brightspace Assignments were not synced for this course. "
            "Content is secondary evidence only."
        )
    else:
        availability = (
            "Assignments were synced, but there is no matching Assignment object for this identifier. "
            "That does not mean the homework does not exist in the course."
        )
    due = (
        "If Content explicitly states a due date for this same identifier (e.g. \"HW3 is due …\"), "
        "you may report it and MUST say it comes from course Content, not a Brightspace Assignment DueDate. "
        "Never treat Starts/Ends/Available until as a due date."
    )
    submit = (
        "Do not invent a Brightspace Dropbox or Assignments URL. "
        "If Content states a submission location, cite it. "
        "Otherwise say no Assignment submission page was found."
    )
    instructions = (
        "Answer from Content that explicitly mentions this identifier. Cite those Content sources."
    )
    if aspect == AssignmentAspect.DUE:
        aspect_rule = due
    elif aspect in {AssignmentAspect.SUBMIT, AssignmentAspect.OPEN}:
        aspect_rule = submit
    else:
        aspect_rule = instructions
    return (
        "NAMED ASSIGNMENT FALLBACK (Assignment-first, not Assignment-only):\n"
        f"  {availability}\n"
        f"  {aspect_rule}\n"
        "  Prefer chunks marked Explicit identifier match. "
        "If Assignment and Content both lack evidence, say the synced materials do not contain it."
    )


def format_due_at(due_at: str) -> str:
    dt = datetime.fromisoformat(due_at.replace("Z", "+00:00")).astimezone(_STUDENT_TZ)
    return dt.strftime("%b %d, %Y %I:%M %p PT")


def _chinese(question: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", question))


def assignment_source_reference(obj: AssignmentObject, rank: int = 1) -> SourceReference:
    excerpt = f"Due {format_due_at(obj.due_at)}" if obj.due_at else "No due date listed in Assignments"
    return SourceReference(
        id=f"assignment_{obj.object_id}",
        rank=rank,
        title=obj.name,
        module="Assignments",
        url=obj.canonical_url,
        content_type="assignment",
        label=f"Assignments · {obj.name}",
        excerpt=excerpt,
    )


def assignment_citation(obj: AssignmentObject, rank: int = 1) -> Citation:
    ref = assignment_source_reference(obj, rank)
    return Citation(
        rank=rank,
        topic_title=obj.name,
        module="Assignments",
        page=None,
        url=obj.canonical_url,
        excerpt=ref.excerpt,
    )


def structured_assignment_answer(
    obj: AssignmentObject,
    aspect: AssignmentAspect,
    question: str,
) -> str:
    zh = _chinese(question)
    ref = assignment_source_reference(obj)
    if aspect == AssignmentAspect.DUE:
        if not obj.due_at:
            if zh:
                return (
                    f"Brightspace Assignments 里的「{obj.name}」没有列出 due date。"
                    f"当前同步材料中没有可靠的截止时间。 [SOURCE {ref.rank}]"
                )
            return (
                f"The Brightspace assignment “{obj.name}” does not list a due date. "
                f"Synced materials do not contain a reliable deadline. [SOURCE {ref.rank}]"
            )
        when = format_due_at(obj.due_at)
        if zh:
            return f"「{obj.name}」的截止时间是 {when}（来自 Brightspace Assignments）。 [SOURCE {ref.rank}]"
        return f"{obj.name} is due {when} (Brightspace Assignments due date). [SOURCE {ref.rank}]"

    submit = obj.submission_type or "file"
    if aspect == AssignmentAspect.SUBMIT:
        if zh:
            return (
                f"「{obj.name}」请在 Brightspace Assignments 的 dropbox 提交（类型：{submit}）。"
                f"点击来源打开提交页。 [SOURCE {ref.rank}]"
            )
        return (
            f"Submit {obj.name} in the Brightspace Assignments dropbox ({submit}). "
            f"Open the source link to go to the folder. [SOURCE {ref.rank}]"
        )

    if zh:
        return f"点击来源打开 Brightspace 中的「{obj.name}」作业文件夹。 [SOURCE {ref.rank}]"
    return f"Open {obj.name} in Brightspace Assignments. [SOURCE {ref.rank}]"
