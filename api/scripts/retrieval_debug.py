#!/usr/bin/env python3
"""Print RAW Top-K retrieval results without LLM.

Usage:
  python scripts/retrieval_debug.py --course-id <uuid> --question "When is the final exam?"
  python scripts/retrieval_debug.py --list-courses
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.chroma_store import find_course_by_id, list_all_courses, search_chunks


def print_results(course_id: UUID, question: str, top_k: int) -> None:
    course = find_course_by_id(course_id)
    if not course:
        print(f"Course not found: {course_id}")
        sys.exit(1)

    print("=" * 60)
    print("CourseBrain Retrieval Debug")
    print("=" * 60)
    print(f"Course:      {course['name']}")
    print(f"Course ID:   {course_id}")
    print(f"Collection:  course_{course['id']}")
    print(f"Question:    {question}")
    print(f"Embedding:   {settings.embedding_model}")
    print(f"Top K:       {top_k}")
    print("=" * 60)


async def run(course_id: UUID, question: str, top_k: int) -> None:
    print_results(course_id, question, top_k)
    hits = await search_chunks(course_id, question, top_k)

    if not hits:
        print("No results. Is the course synced?")
        return

    for hit in hits:
        page = f"Page: {hit.source.page}" if hit.source.page else "Page: n/a"
        module = hit.source.module or "n/a"
        print(f"\n#{hit.rank}")
        print(f"Score:     {hit.score:.4f}  (distance: {hit.distance:.4f})")
        print(f"Source:    {hit.source.topic_title}")
        print(f"{page}")
        print(f"Module:    {module}")
        print(f"URL:       {hit.source.url}")
        print(f"Text:\n{hit.text[:500]}{'...' if len(hit.text) > 500 else ''}")

    print("\n" + "=" * 60)
    print(f"Returned {len(hits)} chunk(s)")


def list_courses() -> None:
    courses = list_all_courses()
    if not courses:
        print("No synced courses found.")
        return
    print(json.dumps([c.model_dump(mode="json") for c in courses], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug CourseBrain vector retrieval")
    parser.add_argument("--course-id", type=str, help="Internal course UUID")
    parser.add_argument("--question", "-q", type=str, help="Search question")
    parser.add_argument("--top-k", type=int, default=5, help="Top K (default: 5)")
    parser.add_argument("--list-courses", action="store_true", help="List synced courses")
    args = parser.parse_args()

    if args.list_courses:
        list_courses()
        return

    if not args.course_id or not args.question:
        parser.error("--course-id and --question are required (or use --list-courses)")

    asyncio.run(run(UUID(args.course_id), args.question, args.top_k))


if __name__ == "__main__":
    main()
