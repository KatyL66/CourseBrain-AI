#!/usr/bin/env python3
"""Run full RAG pipeline and print retrieval, context, messages, and answer."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.chroma_store import find_course_by_id
from app.services.rag import chat_with_rag


def print_section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


async def run(course_id: UUID, question: str) -> None:
    course = find_course_by_id(course_id)
    if not course:
        print(f"Course not found: {course_id}")
        sys.exit(1)

    print_section("CourseBrain RAG Debug")
    print(f"Course:    {course['name']}")
    print(f"Question:  {question}")
    print(f"Model:     {settings.chat_model}")
    print(f"Embedding: {settings.embedding_model}")

    answer, intent, cited_refs, all_refs, retrieved, debug = await chat_with_rag(
        course_id, question, include_debug=True,
    )
    print(f"Intent:    {intent.intent.value} (confidence={intent.confidence:.2f})")
    print(f"Type:      {intent.question_type.value}")
    print(f"Queries:   {intent.search_queries}")
    if not debug:
        print("Debug info unavailable.")
        return

    print_section("Retrieved Top 5")
    for hit in debug.retrieval:
        page = hit.source.page if hit.source.page is not None else "n/a"
        print(f"\n#{hit.rank}  score={hit.score:.4f}")
        print(f"  File:   {hit.source.topic_title}")
        print(f"  Page:   {page}")
        print(f"  Module: {hit.source.module or 'n/a'}")
        print(f"  Text:   {hit.text[:200]}...")

    print_section("RAG Context Sent to LLM")
    print(debug.rag_context[:3000])
    if len(debug.rag_context) > 3000:
        print(f"\n... ({len(debug.rag_context) - 3000} more chars truncated)")

    print_section("Final Messages to LLM")
    print(json.dumps(debug.messages, indent=2, ensure_ascii=False)[:4000])

    print_section("Final Answer")
    print(answer)

    print_section("Referenced in Answer")
    print(json.dumps([r.model_dump() for r in cited_refs], indent=2, ensure_ascii=False))

    print_section("All Source References")
    print(json.dumps([r.model_dump() for r in all_refs], indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug CourseBrain RAG chat pipeline")
    parser.add_argument("--course-id", required=True, help="Internal course UUID")
    parser.add_argument("--question", "-q", required=True, help="User question")
    args = parser.parse_args()
    asyncio.run(run(UUID(args.course_id), args.question))


if __name__ == "__main__":
    main()
