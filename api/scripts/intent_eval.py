#!/usr/bin/env python3
"""Evaluate query intent classifier on fixed + unseen test cases."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.query_intent import QueryIntent, classify_query_intent


@dataclass
class EvalCase:
    question: str
    expected: QueryIntent
    suite: str


# Original routing-calibrated cases
CORE_CASES = [
    EvalCase("When is the final exam?", QueryIntent.COURSE_INFO, "core"),
    EvalCase("What is a project manager?", QueryIntent.LEARNING, "core"),
    EvalCase("Explain CPM to me.", QueryIntent.LEARNING, "core"),
    EvalCase("What do I submit for HW3?", QueryIntent.ASSIGNMENT, "core"),
    EvalCase("How much is the final worth?", QueryIntent.COURSE_INFO, "core"),
    EvalCase("Explain Newton's method.", QueryIntent.LEARNING, "core"),
    EvalCase("What's the late penalty for Homework 2?", QueryIntent.ASSIGNMENT, "core"),
    EvalCase("What topics should I study for the final?", QueryIntent.LEARNING, "core"),
]

# Unseen boundary cases — NOT copied into classifier prompt
UNSEEN_CASES = [
    EvalCase("Where is the midterm held?", QueryIntent.COURSE_INFO, "unseen"),
    EvalCase("Define critical path in project scheduling.", QueryIntent.LEARNING, "unseen"),
    EvalCase("Is attendance mandatory for this class?", QueryIntent.COURSE_INFO, "unseen"),
    EvalCase("What file format should the team report use?", QueryIntent.ASSIGNMENT, "unseen"),
    EvalCase("Compare agile and waterfall for software projects.", QueryIntent.LEARNING, "unseen"),
    EvalCase("Who is the TA for this course?", QueryIntent.COURSE_INFO, "unseen"),
    EvalCase("Can I submit the decision-tree homework one day late?", QueryIntent.ASSIGNMENT, "unseen"),
    EvalCase("Summarize the Week 4 lecture on risk management.", QueryIntent.LEARNING, "unseen"),
    EvalCase("When are the professor's office hours?", QueryIntent.COURSE_INFO, "unseen"),
    EvalCase("What is the rubric for the final project presentation?", QueryIntent.ASSIGNMENT, "unseen"),
    EvalCase(
        "The syllabus says the final covers Weeks 5-10. What are the key concepts from Week 7?",
        QueryIntent.MIXED,
        "unseen",
    ),
    EvalCase("What topics from Chapter 7 will be on the final?", QueryIntent.MIXED, "unseen"),
]


async def run_eval(cases: list[EvalCase]) -> list[tuple[EvalCase, str, float, bool]]:
    results = []
    for case in cases:
        r = await classify_query_intent(case.question)
        ok = r.intent == case.expected
        results.append((case, r.intent.value, r.confidence, ok))
    return results


def print_table(results: list[tuple[EvalCase, str, float, bool]]) -> int:
    passed = sum(1 for *_, ok in results if ok)
    print(f"\n{'SUITE':<8} {'PASS':<5} {'EXPECTED':<12} {'ACTUAL':<12} {'CONF':<6} QUESTION")
    print("-" * 100)
    for case, actual, conf, ok in results:
        mark = "yes" if ok else "NO"
        print(
            f"{case.suite:<8} {mark:<5} {case.expected.value:<12} {actual:<12} {conf:<6.2f} {case.question}"
        )
    print("-" * 100)
    print(f"Total: {passed}/{len(results)} passed ({100 * passed / len(results):.0f}%)")
    print("Note: confidence is LLM self-reported — use for debug only, not as reliability metric.")
    return passed


async def main() -> None:
    all_cases = CORE_CASES + UNSEEN_CASES
    results = await run_eval(all_cases)
    core = [r for r in results if r[0].suite == "core"]
    unseen = [r for r in results if r[0].suite == "unseen"]

    print("=" * 100)
    print("CORE CASES (routing-calibrated)")
    core_pass = print_table(core)

    print("\n" + "=" * 100)
    print("UNSEEN CASES (generalization check)")
    unseen_pass = print_table(unseen)

    print(f"\nOverall: {core_pass + unseen_pass}/{len(all_cases)}")


if __name__ == "__main__":
    asyncio.run(main())
