"""LLM-based query planning: intent classification + retrieval query generation."""

from __future__ import annotations

import logging
import re
from enum import Enum

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.services.identifier_match import extract_identifiers

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You classify student questions and plan retrieval queries for course-material search.

Return structured output with:
- intent: WHERE TO SEARCH FIRST (retrieval routing label)
- topic: short normalized topic (e.g. "system", "final exam", "HW3")
- question_type: what kind of answer the student needs
- search_queries: MINIMUM set of English retrieval queries for course materials
- confidence: 0.0-1.0

INTENT (retrieval routing — not a linguistic category):

COURSE_INFO
Administrative/logistics: syllabus, schedule, announcements.
Examples: exam date/time/location, grading weight, attendance, office hours.

LEARNING
Instructional materials: lectures, slides, readings, notes.
Examples: definitions, concept explanations, methods, formulas, comparisons, what to study.

ASSIGNMENT
Specific homework, assignment, project, deliverable, or rubric.
Examples: submission requirements, formatting, rubric criteria.
If a named assignment is mentioned (e.g. "HW3"), prefer ASSIGNMENT.
Do NOT use ASSIGNMENT for course-wide grading policy (what percent homework is of the total grade, late policy for the course). That is COURSE_INFO / syllabus.

MIXED
ONLY when answering genuinely requires multiple source categories.
Rare — do not use just because the question mentions words from multiple categories.

QUESTION_TYPE values:
factual_lookup | definition | concept_explanation | example | comparison | procedure | assignment_help | other

SEARCH QUERY PLANNING — generate the MINIMUM queries needed to answer completely:

1. Prefer 1 query for narrow factual questions (dates, locations, single facts).
2. Prefer 1 query for explicit definition requests ("definition of X").
3. Prefer 1 query for explicit example requests ("examples of X").
4. Use 2-3 queries for normal concept explanation ("What is X?" without narrowing).
5. Allow up to 4 queries ONLY when the user asks for detailed explanation or genuinely needs multiple aspects.
6. Queries must be optimized for retrieving COURSE MATERIALS, not for generating an answer.
7. Generate retrieval queries in ENGLISH when course terminology is English, even if the user asks in Chinese.
8. Do NOT invent course-specific facts, dates, names, or policies in search queries.
9. Preserve existing intent routing behavior.

Examples:

User: "When is the final exam?"
{
  "intent": "COURSE_INFO",
  "topic": "final exam",
  "question_type": "factual_lookup",
  "search_queries": ["final exam date and time"]
}

User: "What is the definition of a system?"
{
  "intent": "LEARNING",
  "topic": "system",
  "question_type": "definition",
  "search_queries": ["definition of a system"]
}

User: "What is a system?"
{
  "intent": "LEARNING",
  "topic": "system",
  "question_type": "concept_explanation",
  "search_queries": [
    "system definition",
    "key characteristics of a system",
    "examples of systems"
  ]
}

User: "Explain system to me in detail. I'm confused."
{
  "intent": "LEARNING",
  "topic": "system",
  "question_type": "concept_explanation",
  "search_queries": [
    "system definition",
    "key characteristics of a system",
    "emergent behavior in systems",
    "examples of systems"
  ]
}

User: "Give me examples of systems."
{
  "intent": "LEARNING",
  "topic": "system",
  "question_type": "example",
  "search_queries": ["examples of systems"]
}

User: "How much is the final worth?"
{
  "intent": "COURSE_INFO",
  "topic": "final exam grading weight",
  "question_type": "factual_lookup",
  "search_queries": ["final exam grading weight"]
}

User: "作业占比总成绩百分之多少"
{
  "intent": "COURSE_INFO",
  "topic": "homework grading weight",
  "question_type": "factual_lookup",
  "search_queries": ["course grading breakdown", "homework percent of final grade"]
}
{
  "intent": "ASSIGNMENT",
  "topic": "HW3",
  "question_type": "assignment_help",
  "search_queries": ["HW3 submission requirements"]
}

User: "Compare CPM and PERT."
{
  "intent": "LEARNING",
  "topic": "CPM and PERT",
  "question_type": "comparison",
  "search_queries": ["CPM and PERT comparison", "differences between CPM and PERT"]
}

User: "When should I use Newton's method?"
{
  "intent": "LEARNING",
  "topic": "Newton's method",
  "question_type": "procedure",
  "search_queries": ["when to use Newton's method"]
}

User: "什么是 system？"
{
  "intent": "LEARNING",
  "topic": "system",
  "question_type": "concept_explanation",
  "search_queries": [
    "system definition",
    "key characteristics of a system",
    "examples of systems"
  ]
}"""


_NAMED_WORK_KINDS = frozenset({"hw", "assignment", "lab", "project", "quiz"})
_COURSE_WIDE_POLICY = re.compile(
    r"占比|总成绩|总分|成绩构成|评分构成|平时成绩|"
    r"占(?:比)?(?:整个|全部)?\s*(?:grade|成绩|总分)|"
    r"作业.{0,24}占|"
    r"\bgrading\s+(weight|breakdown|scheme|policy)\b|"
    r"\bgrade\s+(breakdown|weights?|composition)\b|"
    r"percent(?:age)?\s+of\s+(?:the\s+)?(?:final\s+)?grade|"
    r"(?:how much|what percent).{0,24}(?:homework|assignments?|quizzes?|labs?|作业)|"
    r"(?:homework|assignments?|作业).{0,16}(?:worth|weight|percent|占比)",
    re.I,
)


def _has_named_work_item(question: str) -> bool:
    return any(
        ident.number is not None and ident.kind in _NAMED_WORK_KINDS
        for ident in extract_identifiers(question)
    )


def is_course_wide_policy_question(question: str) -> bool:
    """True for syllabus-level grade weights, not a named HW/lab/quiz."""
    if not question or _has_named_work_item(question):
        return False
    return bool(_COURSE_WIDE_POLICY.search(question))


class QueryIntent(str, Enum):
    COURSE_INFO = "COURSE_INFO"
    LEARNING = "LEARNING"
    ASSIGNMENT = "ASSIGNMENT"
    MIXED = "MIXED"


class QuestionType(str, Enum):
    FACTUAL_LOOKUP = "factual_lookup"
    DEFINITION = "definition"
    CONCEPT_EXPLANATION = "concept_explanation"
    EXAMPLE = "example"
    COMPARISON = "comparison"
    PROCEDURE = "procedure"
    ASSIGNMENT_HELP = "assignment_help"
    OTHER = "other"


MAX_SEARCH_QUERIES = 4

INTENT_QUERY_LIMITS: dict[QueryIntent, int] = {
    QueryIntent.COURSE_INFO: 1,
    QueryIntent.ASSIGNMENT: 2,
    QueryIntent.LEARNING: 3,
    QueryIntent.MIXED: 3,
}

QUESTION_TYPE_QUERY_LIMITS: dict[QuestionType, int] = {
    QuestionType.FACTUAL_LOOKUP: 1,
    QuestionType.DEFINITION: 1,
    QuestionType.EXAMPLE: 1,
    QuestionType.COMPARISON: 2,
    QuestionType.PROCEDURE: 2,
    QuestionType.ASSIGNMENT_HELP: 2,
    QuestionType.CONCEPT_EXPLANATION: 3,
    QuestionType.OTHER: 3,
}


class QueryIntentResult(BaseModel):
    """Query plan returned by the planner (backward-compatible name)."""

    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    topic: str | None = None
    question_type: QuestionType = QuestionType.OTHER
    search_queries: list[str] = Field(default_factory=list)


class _LlmQueryPlan(BaseModel):
    intent: QueryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    topic: str | None = None
    question_type: QuestionType = QuestionType.OTHER
    search_queries: list[str] = Field(min_length=1, max_length=MAX_SEARCH_QUERIES)

    @field_validator("search_queries")
    @classmethod
    def strip_queries(cls, values: list[str]) -> list[str]:
        cleaned = [q.strip() for q in values if q.strip()]
        if not cleaned:
            raise ValueError("search_queries must contain at least one non-empty query")
        return cleaned


def _cap_search_queries(
    queries: list[str],
    intent: QueryIntent,
    question: str,
    question_type: QuestionType = QuestionType.OTHER,
) -> list[str]:
    """Apply intent/type-based limits and ensure at least one query."""
    intent_limit = INTENT_QUERY_LIMITS.get(intent, MAX_SEARCH_QUERIES)
    type_limit = QUESTION_TYPE_QUERY_LIMITS.get(question_type, MAX_SEARCH_QUERIES)
    limit = min(intent_limit, type_limit, MAX_SEARCH_QUERIES)
    capped = queries[:limit]
    if not capped:
        return [question.strip()]
    return capped


def _fallback_plan(question: str, intent: QueryIntent = QueryIntent.LEARNING) -> QueryIntentResult:
    q = question.strip()
    return QueryIntentResult(
        intent=intent,
        confidence=0.0,
        topic=None,
        question_type=QuestionType.OTHER,
        search_queries=[q],
    )


def log_plan_debug(question: str, result: QueryIntentResult) -> None:
    if not settings.debug_mode:
        return
    queries = "\n".join(f"  - {q}" for q in result.search_queries)
    logger.info(
        "QUESTION:\n%s\n\nINTENT: %s\nCONFIDENCE: %.2f\nTOPIC: %s\nQUESTION_TYPE: %s\n"
        "SEARCH_QUERIES:\n%s",
        question,
        result.intent.value,
        result.confidence,
        result.topic or "n/a",
        result.question_type.value,
        queries,
    )


async def plan_query(
    question: str,
    *,
    client: AsyncOpenAI | None = None,
) -> QueryIntentResult:
    """Plan retrieval: intent routing + search queries in one LLM call."""
    q = question.strip()
    if not q:
        return _fallback_plan("", QueryIntent.MIXED)

    if not settings.openai_api_key:
        fallback = _fallback_plan(q)
        log_plan_debug(q, fallback)
        return fallback

    llm = client or AsyncOpenAI(api_key=settings.openai_api_key)
    response = await llm.beta.chat.completions.parse(
        model=settings.chat_model,
        messages=[
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": q},
        ],
        response_format=_LlmQueryPlan,
        temperature=0,
    )
    parsed = response.choices[0].message.parsed
    if not parsed:
        fallback = _fallback_plan(q, QueryIntent.MIXED)
        log_plan_debug(q, fallback)
        return fallback

    search_queries = _cap_search_queries(
        parsed.search_queries, parsed.intent, q, parsed.question_type,
    )
    intent = parsed.intent
    question_type = parsed.question_type
    if is_course_wide_policy_question(q):
        intent = QueryIntent.COURSE_INFO
        if question_type == QuestionType.ASSIGNMENT_HELP:
            question_type = QuestionType.FACTUAL_LOOKUP
        search_queries = [
            query for query in search_queries
            if not _has_named_work_item(query)
        ] or ["course grading policy"]
        search_queries = _cap_search_queries(search_queries, intent, q, question_type)

    result = QueryIntentResult(
        intent=intent,
        confidence=parsed.confidence,
        topic=parsed.topic,
        question_type=question_type,
        search_queries=search_queries,
    )
    log_plan_debug(q, result)
    return result


async def classify_query_intent(
    question: str,
    *,
    client: AsyncOpenAI | None = None,
) -> QueryIntentResult:
    """Backward-compatible alias for plan_query."""
    return await plan_query(question, client=client)
