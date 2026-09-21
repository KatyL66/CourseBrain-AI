"""Deterministic document-level content type classification for RAG routing."""

from __future__ import annotations

import re
from enum import Enum

from app.models.schemas import TopicIngest
from app.services.chunker import strip_html
from app.services.grade_policy import looks_like_course_level_grading

CONTENT_TYPES = frozenset({"syllabus", "lecture", "assignment", "announcement", "other"})


class ContentType(str, Enum):
    SYLLABUS = "syllabus"
    LECTURE = "lecture"
    ASSIGNMENT = "assignment"
    ANNOUNCEMENT = "announcement"
    OTHER = "other"


_SYLLABUS = re.compile(
    r"\bsyllabus\b|课程大纲|教学大纲|grading\s+polic(?:y|ies)|points\s+breakdown",
    re.IGNORECASE,
)
_ANNOUNCEMENT = re.compile(
    r"\bannouncements?\b|公告",
    re.IGNORECASE,
)
_ASSIGNMENT = re.compile(
    r"\b(homework|assignment|assignments|deliverable|rubric|worksheet|workshop)\b"
    r"|\bhw\s*\d+\b"
    r"|\bproject\s+(guidelines?|instructions?|requirements?|description|rubric)\b"
    r"|\bfinal\s+project\b"
    r"|\bteam\s+(project|report|deliverable)\b"
    r"|\bdecision-tree\s+(homework|assignment)\b"
    r"|\bms\s+project\s+assignment\b"
    r"|作业|项目要求",
    re.IGNORECASE,
)
_LECTURE = re.compile(
    r"\b(lecture|lectures|slides?|presentation|chapter|lab\s+session)\b"
    r"|\bproject\s+management\b.*\b(fundamentals?|lecture|introduction|overview)\b"
    r"|\bproject\s+management\s+(fundamentals?|lecture)\b"
    r"|\bweek\s*\d+\b"
    r"|\blecture\s*\d+\b"
    r"|课件|讲义",
    re.IGNORECASE,
)
_REFERENCES = re.compile(
    r"\breferences?\b|\badditional\s+reading\b|参考资料",
    re.IGNORECASE,
)


def _haystack(topic: TopicIngest) -> str:
    parts = [
        topic.title or "",
        topic.module_name or "",
        topic.url or "",
    ]
    return " ".join(parts).lower()


def _topic_body(topic: TopicIngest, body: str | None = None) -> str:
    if body and body.strip():
        return body
    raw = topic.content or ""
    if not raw:
        return ""
    if "<" in raw:
        return strip_html(raw)
    return raw


def classify_document(topic: TopicIngest, body: str | None = None) -> ContentType:
    """Classify from title/module metadata and document body — not folder-name guesses.

    "Overview" is not automatically syllabus. A welcome page stays other; a page
    that actually states course-wide grading becomes syllabus.
    """
    meta = _haystack(topic)
    module = (topic.module_name or "").strip().lower()
    text_body = _topic_body(topic, body)

    if module == "syllabus" or _SYLLABUS.search(meta):
        return ContentType.SYLLABUS
    if _ASSIGNMENT.search(meta):
        return ContentType.ASSIGNMENT
    if looks_like_course_level_grading(text_body):
        return ContentType.SYLLABUS
    if module == "announcements" or _ANNOUNCEMENT.search(meta):
        return ContentType.ANNOUNCEMENT
    if _REFERENCES.search(meta):
        return ContentType.OTHER
    if _LECTURE.search(meta):
        return ContentType.LECTURE
    return ContentType.OTHER
