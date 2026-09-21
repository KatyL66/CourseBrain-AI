#!/usr/bin/env python3
"""Evaluate Query Planner output (planner-only — no Chroma retrieval)."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.query_intent import QuestionType, QueryIntent, plan_query


@dataclass
class PlannerEvalCase:
    question: str
    expected_intent: QueryIntent | None = None
    min_queries: int = 1
    max_queries: int = 4
    expected_question_type: QuestionType | None = None
    notes: str = ""


EVAL_CASES = [
    PlannerEvalCase(
        "When is the final exam?",
        QueryIntent.COURSE_INFO,
        1,
        1,
        QuestionType.FACTUAL_LOOKUP,
        "narrow factual",
    ),
    PlannerEvalCase(
        "final几点？",
        QueryIntent.COURSE_INFO,
        1,
        1,
        notes="Chinese → English retrieval queries",
    ),
    PlannerEvalCase(
        "What is a system?",
        QueryIntent.LEARNING,
        2,
        3,
        QuestionType.CONCEPT_EXPLANATION,
        "concept explanation expands",
    ),
    PlannerEvalCase(
        "什么是system？",
        QueryIntent.LEARNING,
        2,
        3,
        QuestionType.CONCEPT_EXPLANATION,
        "Chinese question, English queries",
    ),
    PlannerEvalCase(
        "What is the definition of a system?",
        QueryIntent.LEARNING,
        1,
        1,
        QuestionType.DEFINITION,
        "explicit definition stays narrow",
    ),
    PlannerEvalCase(
        "Give me examples of systems.",
        QueryIntent.LEARNING,
        1,
        1,
        QuestionType.EXAMPLE,
        "explicit example stays narrow",
    ),
    PlannerEvalCase(
        "Explain system to me in detail. I'm confused.",
        QueryIntent.LEARNING,
        3,
        4,
        QuestionType.CONCEPT_EXPLANATION,
        "detailed explanation may use up to 4",
    ),
    PlannerEvalCase(
        "What do I need to submit for HW3?",
        QueryIntent.ASSIGNMENT,
        1,
        2,
        QuestionType.ASSIGNMENT_HELP,
    ),
    PlannerEvalCase(
        "Compare CPM and PERT.",
        QueryIntent.LEARNING,
        1,
        2,
        QuestionType.COMPARISON,
    ),
    PlannerEvalCase(
        "When should I use Newton's method?",
        QueryIntent.LEARNING,
        1,
        2,
        QuestionType.PROCEDURE,
    ),
]


def _check(case: PlannerEvalCase, plan) -> list[str]:
    issues: list[str] = []
    n = len(plan.search_queries)

    if case.expected_intent and plan.intent != case.expected_intent:
        issues.append(f"intent: expected {case.expected_intent.value}, got {plan.intent.value}")

    if n < case.min_queries or n > case.max_queries:
        issues.append(f"query count: expected {case.min_queries}-{case.max_queries}, got {n}")

    if case.expected_question_type and plan.question_type != case.expected_question_type:
        issues.append(
            f"question_type: expected {case.expected_question_type.value}, "
            f"got {plan.question_type.value}"
        )

    for q in plan.search_queries:
        if not q.strip():
            issues.append("empty search query")
    return issues


async def main() -> None:
    print("Query Planner Evaluation (planner-only, no Chroma)\n")
    print("=" * 80)

    passed = 0
    for i, case in enumerate(EVAL_CASES, start=1):
        plan = await plan_query(case.question)
        issues = _check(case, plan)
        ok = not issues
        if ok:
            passed += 1

        print(f"\n[{i}] QUESTION: {case.question}")
        print(f"    INTENT:         {plan.intent.value}")
        print(f"    TOPIC:          {plan.topic or 'n/a'}")
        print(f"    QUESTION_TYPE:  {plan.question_type.value}")
        print(f"    CONFIDENCE:     {plan.confidence:.2f}")
        print("    SEARCH_QUERIES:")
        for j, q in enumerate(plan.search_queries, start=1):
            print(f"      {j}. {q}")
        if case.notes:
            print(f"    NOTE: {case.notes}")
        if issues:
            print(f"    ISSUES: {'; '.join(issues)}")
        else:
            print("    CHECK:  OK")

    print("\n" + "=" * 80)
    print(f"Structural checks: {passed}/{len(EVAL_CASES)} passed")
    print("\nManual review:")
    print("- Did narrow questions stay narrow?")
    print("- Did concept explanation questions expand appropriately?")
    print("- Did Chinese questions generate useful English retrieval queries?")
    print("- Did the planner avoid inventing course-specific information?")


if __name__ == "__main__":
    asyncio.run(main())
