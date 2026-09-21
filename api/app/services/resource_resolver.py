"""Course resource resolution: map user mentions (lab2, hw1) to synced resources via metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from app.db.chroma_store import _with_collection, find_course_by_id, is_hnsw_missing_on_disk, query_chunks
from app.services.identifier_match import CourseIdentifier, extract_identifiers
from app.services.query_intent import QueryIntent, QueryIntentResult, QuestionType

# Minimum confidence to treat a single match as authoritative for scoped retrieval.
HIGH_CONFIDENCE = 0.85

# Patterns to parse resource identity FROM metadata (title / module), not chunk body.
_TITLE_IDENTITY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("lab", re.compile(r"^lab\s*#?\s*(\d+)\b", re.I)),
    ("hw", re.compile(r"^(?:hw|homework)\s*#?\s*(\d+)\b", re.I)),
    ("lecture", re.compile(r"^lecture\s*[-–—]?\s*(\d+[a-z]?)\b", re.I)),
    ("assignment", re.compile(r"^assignment\s*#?\s*(\d+)\b", re.I)),
    ("quiz", re.compile(r"^quiz\s*#?\s*(\d+)\b", re.I)),
    ("project", re.compile(r"^project\s*#?\s*(\d+)\b", re.I)),
    ("week", re.compile(r"^week\s*#?\s*(\d+)\b", re.I)),
    ("chapter", re.compile(r"^(?:chapter|ch\.?)\s*#?\s*(\d+)\b", re.I)),
]

_MODULE_TAIL_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("lab", re.compile(r"(?:^|>)\s*lab\s*#?\s*(\d+)\s*$", re.I)),
    ("hw", re.compile(r"(?:^|>)\s*(?:hw|homework)\s*#?\s*(\d+)\s*$", re.I)),
    ("lecture", re.compile(r"(?:^|>)\s*lecture\s*#?\s*(\d+[a-z]?)\s*$", re.I)),
    ("assignment", re.compile(r"(?:^|>)\s*assignment\s*#?\s*(\d+)\s*$", re.I)),
    ("quiz", re.compile(r"(?:^|>)\s*quiz\s*#?\s*(\d+)\s*$", re.I)),
    ("project", re.compile(r"(?:^|>)\s*project\s*#?\s*(\d+)\s*$", re.I)),
    ("week", re.compile(r"(?:^|>)\s*week\s*#?\s*(\d+)\s*$", re.I)),
]

# Schedule-like titles mention lab numbers in body but are not lab-N resources.
_SCHEDULE_TITLE = re.compile(r"\bschedule\b", re.I)

_LOGISTICS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bwhen\b", re.I),
    re.compile(r"\bdeadline\b", re.I),
    re.compile(r"\bdue\s+date\b", re.I),
    re.compile(r"\bwhat\s+time\b", re.I),
    re.compile(r"\bwhat\s+day\b", re.I),
    re.compile(r"什么时候"),
    re.compile(r"哪天"),
    re.compile(r"何时"),
    re.compile(r"截止"),
    re.compile(r"交吗"),
    re.compile(r"占多少分"),
    re.compile(r"\bweight\b", re.I),
    re.compile(r"\bgrading\b", re.I),
    re.compile(r"\bpercent\b", re.I),
]

_CONTENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bobjective\b", re.I),
    re.compile(r"\bprocedure\b", re.I),
    re.compile(r"\brequirement", re.I),
    re.compile(r"\bdeliverable", re.I),
    re.compile(r"\brubric\b", re.I),
    re.compile(r"\bwhat\s+to\s+do\b", re.I),
    re.compile(r"\bwhat\s+do\s+i\b", re.I),
    re.compile(r"要干啥"),
    re.compile(r"是什么"),
    re.compile(r"是啥"),
    re.compile(r"讲什么"),
    re.compile(r"做什么"),
    re.compile(r"怎么做"),
    re.compile(r"要交什么"),
    re.compile(r"交什么"),
]


class EvidenceScope(str, Enum):
    """Where to look for answers after a resource is resolved."""

    RESOURCE_CONTENT = "resource_content"
    RESOURCE_LOGISTICS = "resource_logistics"
    GLOBAL = "global"


@dataclass(frozen=True)
class CourseResource:
    topic_external_id: str
    topic_title: str
    module_name: str | None
    content_type: str | None


@dataclass(frozen=True)
class ResourceMatch:
    identifier: CourseIdentifier
    resource: CourseResource
    confidence: float
    match_source: str  # title | module | both


def _parse_title_number(raw: str) -> int | None:
    digits = re.match(r"(\d+)", raw.strip())
    return int(digits.group(1)) if digits else None


def _identity_from_title(title: str) -> CourseIdentifier | None:
    for kind, pattern in _TITLE_IDENTITY_RULES:
        match = pattern.search(title.strip())
        if match:
            number = _parse_title_number(match.group(1))
            if number is not None:
                return CourseIdentifier(kind=kind, number=number)
    return None


def _identity_from_module(module_name: str) -> CourseIdentifier | None:
    if not module_name:
        return None
    tail = module_name.split(">")[-1].strip()
    for kind, pattern in _MODULE_TAIL_RULES:
        match = pattern.search(tail) or pattern.search(module_name)
        if match:
            number = _parse_title_number(match.group(1))
            if number is not None:
                return CourseIdentifier(kind=kind, number=number)
    return None


def resource_identity(resource: CourseResource) -> CourseIdentifier | None:
    """Parse structured identity from resource metadata (title preferred over module)."""
    if _SCHEDULE_TITLE.search(resource.topic_title):
        return None
    title_id = _identity_from_title(resource.topic_title)
    if title_id:
        return title_id
    return _identity_from_module(resource.module_name or "")


def _score_match(query_id: CourseIdentifier, resource: CourseResource) -> ResourceMatch | None:
    title_id = _identity_from_title(resource.topic_title)
    module_id = _identity_from_module(resource.module_name or "")

    if title_id and title_id.key == query_id.key:
        conf = 0.95
        source = "title"
        if module_id and module_id.key == query_id.key:
            conf = 0.98
            source = "both"
        return ResourceMatch(
            identifier=query_id,
            resource=resource,
            confidence=conf,
            match_source=source,
        )

    if module_id and module_id.key == query_id.key and not _SCHEDULE_TITLE.search(resource.topic_title):
        return ResourceMatch(
            identifier=query_id,
            resource=resource,
            confidence=0.88,
            match_source="module",
        )

    return None


def resolve_resources(
    question: str,
    resources: list[CourseResource],
    *,
    planner_topic: str | None = None,
) -> list[ResourceMatch]:
    """Match query identifiers against course resource metadata."""
    texts = [question]
    if planner_topic and planner_topic.strip():
        texts.append(planner_topic.strip())

    query_ids: list[CourseIdentifier] = []
    seen: set[str] = set()
    for text in texts:
        for ident in extract_identifiers(text):
            if ident.key not in seen:
                seen.add(ident.key)
                query_ids.append(ident)

    if not query_ids:
        return []

    matches: list[ResourceMatch] = []
    for query_id in query_ids:
        for resource in resources:
            hit = _score_match(query_id, resource)
            if hit:
                matches.append(hit)

    # Prefer higher confidence; dedupe by resource id keeping best score.
    best_by_topic: dict[str, ResourceMatch] = {}
    for match in matches:
        tid = match.resource.topic_external_id
        existing = best_by_topic.get(tid)
        if existing is None or match.confidence > existing.confidence:
            best_by_topic[tid] = match

    return sorted(best_by_topic.values(), key=lambda m: -m.confidence)


def unique_high_confidence_match(matches: list[ResourceMatch]) -> ResourceMatch | None:
    if not matches:
        return None
    strong = [m for m in matches if m.confidence >= HIGH_CONFIDENCE]
    if len(strong) != 1:
        return None
    return strong[0]


def _text_has_any_pattern(text: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(text) for p in patterns)


def decide_evidence_scope(
    question: str,
    plan: QueryIntentResult,
    matches: list[ResourceMatch],
) -> EvidenceScope:
    """Decide whether to scope retrieval to resource content, logistics, or global search."""
    if not unique_high_confidence_match(matches):
        return EvidenceScope.GLOBAL

    combined = f"{question} {plan.topic or ''}"

    if plan.intent == QueryIntent.COURSE_INFO:
        return EvidenceScope.RESOURCE_LOGISTICS

    if plan.question_type == QuestionType.FACTUAL_LOOKUP and _text_has_any_pattern(
        combined, _LOGISTICS_PATTERNS,
    ):
        return EvidenceScope.RESOURCE_LOGISTICS

    if _text_has_any_pattern(combined, _LOGISTICS_PATTERNS) and not _text_has_any_pattern(
        combined, _CONTENT_PATTERNS,
    ):
        return EvidenceScope.RESOURCE_LOGISTICS

    if plan.intent == QueryIntent.ASSIGNMENT:
        return EvidenceScope.RESOURCE_CONTENT

    if _text_has_any_pattern(combined, _CONTENT_PATTERNS):
        return EvidenceScope.RESOURCE_CONTENT

    if plan.question_type in (
        QuestionType.ASSIGNMENT_HELP,
        QuestionType.PROCEDURE,
        QuestionType.DEFINITION,
    ):
        return EvidenceScope.RESOURCE_CONTENT

    return EvidenceScope.GLOBAL


async def resolve_course_resources(
    course_id: UUID,
    question: str,
    plan: QueryIntentResult,
) -> tuple[list[ResourceMatch], EvidenceScope]:
    """Load course catalog and resolve identifiers mentioned in the question."""
    catalog = load_course_resources(course_id)
    matches = resolve_resources(question, catalog, planner_topic=plan.topic)
    scope = decide_evidence_scope(question, plan, matches)
    return matches, scope


def load_course_resources(course_id: UUID) -> list[CourseResource]:
    """Unique synced resources (topics) for a course, from Chroma metadata."""
    course = find_course_by_id(course_id)
    if not course:
        return []

    try:
        data = _with_collection(
            course["id"],
            lambda coll: (
                {"metadatas": []}
                if coll.count() == 0
                else coll.get(include=["metadatas"])
            ),
        )
    except Exception as exc:
        if is_hnsw_missing_on_disk(exc):
            return []
        raise
    by_topic: dict[str, CourseResource] = {}
    for meta in data.get("metadatas") or []:
        if not meta:
            continue
        topic_id = meta.get("topic_external_id") or ""
        if not topic_id or topic_id in by_topic:
            continue
        by_topic[topic_id] = CourseResource(
            topic_external_id=topic_id,
            topic_title=meta.get("topic_title") or "",
            module_name=meta.get("module_name") or None,
            content_type=meta.get("content_type") or None,
        )
    return list(by_topic.values())
