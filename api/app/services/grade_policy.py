"""Course-level grading policy vs assignment/project internal scores."""

from __future__ import annotations

import re

from app.models.schemas import SearchResult

# Document body: course-wide composition, not "15 points" on a project rubric.
COURSE_LEVEL_GRADING_RE = re.compile(
    r"grading\s+(polic(?:y|ies)|scheme|breakdown|composition|weights?|information)|"
    r"\bgrade\s+(breakdown|composition|weights?)\b|"
    r"points?\s+breakdown|"
    r"(?:course|total|final|overall)\s+grade|"
    r"of the (?:total|final|course|overall) grade|"
    r"\bgrading\s*:.{0,400}\b(?:homework|assignments?|exams?|quizzes?|project|midterm)\b|"
    r"\bgrading\b.{0,500}\b(?:homework|assignments?|exams?|quizzes?)\b.{0,80}"
    r"(?:\d+\s*%|\d+\s*points?|percent|weight)|"
    r"成绩构成|评分标准|占总成绩|总成绩",
    re.IGNORECASE | re.DOTALL,
)

COURSE_WIDE_POLICY_SCOPE_NOTE = """COURSE-LEVEL POLICY SCOPE:
The student asked about course-wide grading composition (what share of the total course grade is homework, exams, etc.).

Assignment and project INTERNAL point breakdowns are a different scope.
Examples that are NOT course-level grade weights:
- Peer Review 15 points / Report Part I / Partner Evaluation
- Rubric scores inside one homework or the course project

Only use evidence that describes how the COURSE GRADE is composed.
If COURSE CONTEXT has no such evidence, say the synced materials do not currently include the course-wide grading breakdown. Do not convert project/homework rubric points into a course-grade answer."""


def looks_like_course_level_grading(text: str | None) -> bool:
    if not text or not text.strip():
        return False
    return bool(COURSE_LEVEL_GRADING_RE.search(text))


def is_assignment_scoped_source(hit: SearchResult) -> bool:
    source = hit.source
    if (source.source_type or "") == "assignment":
        return True
    if (source.content_type or "") == "assignment":
        return True
    return False


def select_course_level_policy_hits(hits: list[SearchResult]) -> list[SearchResult]:
    """Keep syllabus / course-grade-composition evidence; drop project-level rubrics."""
    kept: list[SearchResult] = []
    for hit in hits:
        if is_assignment_scoped_source(hit):
            continue
        if (hit.source.content_type or "") == "syllabus":
            kept.append(hit)
            continue
        if looks_like_course_level_grading(hit.text):
            kept.append(hit)
    return [hit.model_copy(update={"rank": i}) for i, hit in enumerate(kept, start=1)]


def missing_course_policy_message(question: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", question):
        return (
            "目前同步的课程材料里没有找到这门课整体的 grading breakdown"
            "（例如作业占课程总成绩的比例）。"
            "作业或 Project 内部的分数分配（如 Peer Review、Report Part I）"
            "不能代表课程总评构成。"
        )
    return (
        "The synced course materials do not currently include a course-wide grading breakdown "
        "(for example, what percent of the total course grade is homework). "
        "Internal assignment or project point breakdowns are not the course grade composition."
    )
