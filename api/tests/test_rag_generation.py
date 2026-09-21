import unittest

from app.models.schemas import SearchResult, SourceMetadata
from app.services.query_intent import QuestionType, QueryIntent, QueryIntentResult
from app.services.rag import (
    build_chat_messages,
    extract_referenced_sources,
    format_rag_context,
    hits_to_source_references,
)
from uuid import uuid4


def _hit(page: int, rank: int) -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        rank=rank,
        text=f"slide content page {page}",
        score=0.8,
        distance=0.2,
        source=SourceMetadata(
            course_id="c1",
            content_type="lecture",
            topic_id="t1",
            topic_title="lecture 01a",
            url="https://brightspace.example.com/topic/1",
            module="Content > Week 1",
            page=page,
        ),
    )


class GroundedGenerationTests(unittest.TestCase):
    def test_context_excludes_urls(self):
        context = format_rag_context([_hit(19, 1)])
        self.assertIn("[SOURCE 1]", context)
        self.assertNotIn("brightspace.example.com", context)

    def test_concept_explanation_includes_ta_directive(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            topic="system",
            question_type=QuestionType.CONCEPT_EXPLANATION,
            search_queries=["system definition", "examples of systems"],
        )
        messages = build_chat_messages("什么是 system", "[SOURCE 1]\nContent: test", plan)
        user_content = messages[1]["content"]
        system_content = messages[0]["content"]
        self.assertIn("STUDENT QUESTION:\n什么是 system", user_content)
        self.assertIn("concept_explanation", user_content)
        self.assertIn("Teaching synthesis", system_content)
        self.assertIn("SOURCE LANGUAGE PRESERVATION", system_content)
        self.assertIn("Original definition", system_content)

    def test_named_assignment_fallback_note_appended_to_messages(self):
        from app.services.assignment_query import (
            AssignmentAspect,
            AssignmentLookupStatus,
            named_assignment_content_fallback_note,
        )

        note = named_assignment_content_fallback_note(
            AssignmentAspect.INSTRUCTIONS, AssignmentLookupStatus.MISSING_OBJECT
        )
        messages = build_chat_messages("hw3是啥", "[SOURCE 1]\nContent: HW3 posted", extra_note=note)
        self.assertIn("NAMED ASSIGNMENT FALLBACK", messages[1]["content"])
        self.assertIn("no matching Assignment object", messages[1]["content"])

    def test_prompt_rejects_availability_as_due_date(self):
        messages = build_chat_messages("hw2 due?", "context", None)
        self.assertIn("CONTENT AVAILABILITY IS NOT A DUE DATE", messages[0]["content"])
        self.assertIn("Available until", messages[0]["content"])

    def test_prompt_separates_course_grade_from_project_rubric(self):
        messages = build_chat_messages("这个课作业占整个 grade 的多少？", "context", None)
        self.assertIn("COURSE-LEVEL GRADING vs ASSIGNMENT/PROJECT RUBRICS", messages[0]["content"])
        self.assertIn("Peer Review 15 points", messages[0]["content"])

    def test_context_strips_ends_keeps_hw_due(self):
        chrome = SearchResult(
            chunk_id=uuid4(),
            rank=1,
            text="lecture week 6 Ends Dec 21, 2023 11:59 PM HW 2 due September 9",
            score=0.8,
            distance=0.2,
            source=SourceMetadata(
                course_id="c1",
                content_type="lecture",
                topic_id="t1",
                topic_title="lecture week 6",
                url="https://brightspace.example.com/topic/1",
            ),
        )
        context = format_rag_context([chrome])
        self.assertNotIn("Ends Dec 21", context)
        self.assertIn("HW 2 due September 9", context)

    def test_original_question_not_search_query(self):
        plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.9,
            search_queries=["system definition"],
        )
        messages = build_chat_messages("什么是 system", "context", plan)
        self.assertIn("什么是 system", messages[1]["content"])

    def test_source_references_have_labels(self):
        refs = hits_to_source_references([_hit(19, 1), _hit(20, 2)])
        self.assertEqual(refs[0].id, "source_1")
        self.assertIn("Week 1", refs[0].label)
        self.assertIn("Slide 19", refs[0].label)
        self.assertTrue(refs[0].url.startswith("https://"))

    def test_extract_referenced_sources_from_answer(self):
        refs = hits_to_source_references([_hit(19, 1), _hit(20, 2), _hit(21, 3)])
        answer = "根据 [SOURCE 1] 和 [SOURCE 3]，教授定义了 system。"
        cited = extract_referenced_sources(answer, refs)
        self.assertEqual([r.rank for r in cited], [1, 3])


if __name__ == "__main__":
    unittest.main()
