import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.query_intent import (
    QuestionType,
    QueryIntent,
    QueryIntentResult,
    _cap_search_queries,
    plan_query,
)


def _mock_plan_response(
    *,
    intent: QueryIntent,
    confidence: float = 0.92,
    topic: str | None = "system",
    question_type: QuestionType = QuestionType.CONCEPT_EXPLANATION,
    search_queries: list[str] | None = None,
):
    parsed = QueryIntentResult(
        intent=intent,
        confidence=confidence,
        topic=topic,
        question_type=question_type,
        search_queries=search_queries or ["system definition"],
    )
    choice = MagicMock()
    choice.message.parsed = parsed
    response = MagicMock()
    response.choices = [choice]
    return response


class CapSearchQueriesTests(unittest.TestCase):
    def test_course_info_limited_to_one(self):
        queries = ["final exam date", "final exam location", "final exam policy"]
        capped = _cap_search_queries(queries, QueryIntent.COURSE_INFO, "When is the final?")
        self.assertEqual(len(capped), 1)
        self.assertEqual(capped[0], "final exam date")

    def test_learning_allows_three(self):
        queries = ["a", "b", "c", "d"]
        capped = _cap_search_queries(queries, QueryIntent.LEARNING, "What is X?")
        self.assertEqual(capped, ["a", "b", "c"])

    def test_empty_falls_back_to_question(self):
        capped = _cap_search_queries([], QueryIntent.LEARNING, "What is a system?")
        self.assertEqual(capped, ["What is a system?"])


class QueryPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def _plan(self, question: str, parsed: QueryIntentResult) -> QueryIntentResult:
        mock_client = AsyncMock()
        choice = MagicMock()
        choice.message.parsed = parsed
        response = MagicMock()
        response.choices = [choice]
        mock_client.beta.chat.completions.parse = AsyncMock(return_value=response)

        with patch("app.services.query_intent.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.chat_model = "gpt-4o-mini"
            mock_settings.debug_mode = False
            return await plan_query(question, client=mock_client)

    async def test_returns_full_plan(self):
        llm_plan = QueryIntentResult(
            intent=QueryIntent.LEARNING,
            confidence=0.95,
            topic="system",
            question_type=QuestionType.CONCEPT_EXPLANATION,
            search_queries=[
                "system definition",
                "key characteristics of a system",
                "examples of systems",
            ],
        )
        result = await self._plan("What is a system?", llm_plan)
        self.assertEqual(result.intent, QueryIntent.LEARNING)
        self.assertEqual(result.topic, "system")
        self.assertEqual(result.question_type, QuestionType.CONCEPT_EXPLANATION)
        self.assertEqual(len(result.search_queries), 3)

    async def test_factual_lookup_capped_to_one(self):
        llm_plan = QueryIntentResult(
            intent=QueryIntent.COURSE_INFO,
            confidence=0.98,
            topic="final exam",
            question_type=QuestionType.FACTUAL_LOOKUP,
            search_queries=[
                "final exam date and time",
                "final exam location",
            ],
        )
        result = await self._plan("When is the final exam?", llm_plan)
        self.assertEqual(result.intent, QueryIntent.COURSE_INFO)
        self.assertEqual(len(result.search_queries), 1)

    async def test_no_api_key_fallback(self):
        with patch("app.services.query_intent.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            mock_settings.debug_mode = False
            result = await plan_query("What is a system?")
        self.assertEqual(result.intent, QueryIntent.LEARNING)
        self.assertEqual(result.search_queries, ["What is a system?"])
        self.assertEqual(result.confidence, 0.0)

    async def test_classify_alias_delegates_to_plan_query(self):
        from app.services.query_intent import classify_query_intent

        expected = QueryIntentResult(
            intent=QueryIntent.ASSIGNMENT,
            confidence=0.9,
            topic="HW3",
            question_type=QuestionType.ASSIGNMENT_HELP,
            search_queries=["HW3 submission requirements"],
        )
        with patch("app.services.query_intent.plan_query", AsyncMock(return_value=expected)):
            result = await classify_query_intent("What do I submit for HW3?")
        self.assertEqual(result.search_queries, ["HW3 submission requirements"])

    async def test_overrides_assignment_intent_for_course_wide_grade_weight(self):
        llm_plan = QueryIntentResult(
            intent=QueryIntent.ASSIGNMENT,
            confidence=0.99,
            topic="HW3",
            question_type=QuestionType.ASSIGNMENT_HELP,
            search_queries=["HW3 grading weight", "assignment percent of grade"],
        )
        result = await self._plan("作业占比总成绩百分之多少", llm_plan)
        self.assertEqual(result.intent, QueryIntent.COURSE_INFO)
        self.assertEqual(result.question_type, QuestionType.FACTUAL_LOOKUP)
        self.assertTrue(result.search_queries)
        self.assertFalse(any("HW3" in q or "hw3" in q.lower() for q in result.search_queries))


if __name__ == "__main__":
    unittest.main()
