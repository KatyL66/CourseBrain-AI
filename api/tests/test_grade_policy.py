"""Course-level homework weight vs project milestone points.

Syllabus text may live on an Overview page (module Description),
not in a Syllabus folder. Retrieval must use that page's grading
information and must not treat project rubric points as the course grade.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.schemas import SearchResult, SourceMetadata, TopicIngest
from app.services.assignment_query import AssignmentLookupStatus
from app.services.content_classifier import ContentType, classify_document
from app.services.grade_policy import (
    COURSE_WIDE_POLICY_SCOPE_NOTE,
    looks_like_course_level_grading,
    missing_course_policy_message,
    select_course_level_policy_hits,
)
from app.services.query_intent import (
    QuestionType,
    QueryIntent,
    QueryIntentResult,
    is_course_wide_policy_question,
)
from app.services.rag import build_chat_messages, chat_with_rag
from app.services.retrieval_router import PlannedRetrievalResult, RoutingInfo

COURSE_GRADE_QUESTION = "这个课作业占整个 grade 的多少？"

OVERVIEW_GRADING = (
    "SIM-210 Introduction to Discrete Models\n"
    "Grading\n"
    "Homework: 80 points of the total course grade.\n"
    "Project: 150 points of the total course grade.\n"
    "Exams: 170 points of the total course grade.\n"
)

PROJECT_MILESTONES = (
    "Milestone Schedule: Prototype Sketch Due: Monday, February 3 "
    "Peer Review 12 points Due: Monday, February 10 "
    "Report - Part I (Activities 1,2,3) Due: Friday, February 21 "
    "Report - Part II (Activities 4,5,6) Due: Monday, March 17 "
    "Partner Evaluation 12 points Due: Monday, March 17 "
    "The team will submit one report and all members will receive the same grade."
)


def _topic(**kwargs) -> TopicIngest:
    defaults = {
        "external_id": "1",
        "title": "Untitled",
        "url": "https://lms.example.edu/d2l/le/content/1002/Home",
    }
    defaults.update(kwargs)
    return TopicIngest(**defaults)


def _hit(*, title: str, content_type: str, text: str, source_type: str = "content") -> SearchResult:
    return SearchResult(
        chunk_id=uuid4(),
        rank=0,
        text=text,
        score=0.55,
        distance=0.45,
        source=SourceMetadata(
            course_id="c1",
            content_type=content_type,
            topic_id="t1",
            topic_title=title,
            url="https://lms.example.edu/d2l/le/content/1002/Home",
            module=title,
            source_type=source_type,
        ),
    )


def _plan() -> QueryIntentResult:
    return QueryIntentResult(
        intent=QueryIntent.COURSE_INFO,
        confidence=0.9,
        topic="homework grading weight",
        question_type=QuestionType.FACTUAL_LOOKUP,
        search_queries=["course grading breakdown"],
    )


def _planned(hits: list[SearchResult]) -> PlannedRetrievalResult:
    ranked = [h.model_copy(update={"rank": i}) for i, h in enumerate(hits, start=1)]
    return PlannedRetrievalResult(
        routing=RoutingInfo(
            intent=QueryIntent.COURSE_INFO.value,
            primary_content_types=["syllabus", "announcement"],
            secondary_content_types=["lecture", "other"],
            fallback_content_types=["assignment"],
            tiers_searched=["primary"],
            enough_from_primary=bool(hits),
        ),
        search_queries=["course grading breakdown"],
        per_query=[],
        merged_candidates=[],
        final_results=ranked,
    )


class GradePolicyRegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_original_question_is_course_wide_policy(self):
        self.assertTrue(is_course_wide_policy_question(COURSE_GRADE_QUESTION))

    def test_overview_page_with_grading_classifies_as_syllabus(self):
        topic = _topic(
            title="Overview",
            module_name="Overview",
            content=f"<div>{OVERVIEW_GRADING}</div>",
        )
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_overview_pdf_points_breakdown_is_course_level_grading(self):
        text = (
            "Grading Policies:\n"
            "Points Breakdown -\n"
            "Quizzes 30\n"
            "Homework 80\n"
            "Project 150\n"
            "Exam #1 85\n"
            "Exam #2 85\n"
            "Subtotal 430\n"
            "Final Exam 120\n"
            "Course GRADES will be determined by the distribution of point totals for the class."
        )
        self.assertTrue(looks_like_course_level_grading(text))
        topic = _topic(title="Overview", module_name="Overview", content=text)
        self.assertEqual(classify_document(topic), ContentType.SYLLABUS)

    def test_overview_welcome_page_is_not_syllabus(self):
        topic = _topic(
            title="Overview",
            module_name="Overview",
            content="<p>Welcome to Introduction to Discrete Models. See the weekly modules.</p>",
        )
        self.assertEqual(classify_document(topic), ContentType.OTHER)

    def test_project_milestones_are_not_course_level_grading(self):
        self.assertFalse(looks_like_course_level_grading(PROJECT_MILESTONES))
        topic = _topic(
            title="Project Description",
            module_name="Project",
            content=PROJECT_MILESTONES,
        )
        self.assertEqual(classify_document(topic), ContentType.ASSIGNMENT)

    def test_retrieval_keeps_overview_drops_project_milestones(self):
        overview = _hit(title="Overview", content_type="syllabus", text=OVERVIEW_GRADING)
        project = _hit(
            title="Project Description",
            content_type="assignment",
            text=PROJECT_MILESTONES,
        )
        kept = select_course_level_policy_hits([project, overview])
        titles = [hit.source.topic_title for hit in kept]
        self.assertEqual(titles, ["Overview"])
        self.assertIn("80 points of the total course grade", kept[0].text)
        self.assertNotIn("Peer Review", kept[0].text)

    def test_without_overview_does_not_keep_project_percentages(self):
        project = _hit(
            title="Project Description",
            content_type="assignment",
            text=PROJECT_MILESTONES,
        )
        kept = select_course_level_policy_hits([project])
        self.assertEqual(kept, [])
        message = missing_course_policy_message(COURSE_GRADE_QUESTION)
        self.assertIn("grading breakdown", message)
        self.assertNotIn("12 points", message)
        self.assertNotIn("Partner Evaluation", message)

    def test_generation_note_forbids_project_scope(self):
        messages = build_chat_messages(
            COURSE_GRADE_QUESTION,
            f"[SOURCE 1]\nFile: Overview\nContent:\n{OVERVIEW_GRADING}",
            _plan(),
            extra_note=COURSE_WIDE_POLICY_SCOPE_NOTE,
        )
        user = messages[1]["content"]
        system = messages[0]["content"]
        self.assertIn("COURSE-LEVEL POLICY SCOPE", user)
        self.assertIn("Peer Review 15 points", user)
        self.assertIn("COURSE-LEVEL GRADING vs ASSIGNMENT/PROJECT RUBRICS", system)

    async def test_chat_uses_overview_not_project_description(self):
        overview = _hit(title="Overview", content_type="syllabus", text=OVERVIEW_GRADING)
        project = _hit(
            title="Project Description",
            content_type="assignment",
            text=PROJECT_MILESTONES,
        )
        llm = MagicMock()
        llm.choices = [MagicMock(message=MagicMock(content="根据 [SOURCE 1]，Homework 占 80 points of the total course grade。"))]

        with (
            patch("app.services.rag.plan_query", new=AsyncMock(return_value=_plan())),
            patch(
                "app.services.rag.planned_retrieval",
                new=AsyncMock(return_value=_planned([project, overview])),
            ),
            patch("app.services.rag.lookup_named_assignment", return_value=(AssignmentLookupStatus.NOT_NAMED, None)),
            patch("app.services.rag.settings") as mock_settings,
            patch("app.services.rag.AsyncOpenAI") as mock_openai,
        ):
            mock_settings.openai_api_key = "test-key"
            mock_settings.chat_model = "gpt-4o-mini"
            mock_settings.debug_mode = False
            mock_openai.return_value.chat.completions.create = AsyncMock(return_value=llm)
            answer, _plan_out, referenced, all_refs, _retrieved, _debug = await chat_with_rag(
                uuid4(), COURSE_GRADE_QUESTION,
            )

        titles = [ref.title for ref in all_refs]
        self.assertEqual(titles, ["Overview"])
        self.assertNotIn("Project Description", titles)
        self.assertIn("Overview", [ref.title for ref in referenced])
        create_messages = mock_openai.return_value.chat.completions.create.await_args.kwargs["messages"]
        context = create_messages[1]["content"]
        self.assertIn("80 points of the total course grade", context)
        self.assertIn("File: Overview", context)
        self.assertNotIn("File: Project Description", context)
        self.assertNotIn("Report - Part I (Activities 1,2,3)", context)
        self.assertIn("Homework 占 80 points", answer)

    async def test_chat_without_overview_does_not_guess_project_percentages(self):
        project = _hit(
            title="Project Description",
            content_type="assignment",
            text=PROJECT_MILESTONES,
        )
        with (
            patch("app.services.rag.plan_query", new=AsyncMock(return_value=_plan())),
            patch(
                "app.services.rag.planned_retrieval",
                new=AsyncMock(return_value=_planned([project])),
            ),
            patch("app.services.rag.lookup_named_assignment", return_value=(AssignmentLookupStatus.NOT_NAMED, None)),
            patch("app.services.rag.AsyncOpenAI") as mock_openai,
        ):
            answer, _plan_out, referenced, all_refs, retrieved, _debug = await chat_with_rag(
                uuid4(), COURSE_GRADE_QUESTION,
            )

        mock_openai.assert_not_called()
        self.assertEqual(referenced, [])
        self.assertEqual(all_refs, [])
        self.assertEqual(retrieved, [])
        self.assertIn("grading breakdown", answer)
        self.assertNotIn("12 points", answer)
        self.assertNotIn("Partner Evaluation", answer)


if __name__ == "__main__":
    unittest.main()
