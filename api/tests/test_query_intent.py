import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.query_intent import (
    QuestionType,
    QueryIntent,
    QueryIntentResult,
    classify_query_intent,
    plan_query,
)


def _mock_parse_response(intent: QueryIntent, confidence: float = 0.92):
    parsed = QueryIntentResult(
        intent=intent,
        confidence=confidence,
        topic="test topic",
        question_type=QuestionType.OTHER,
        search_queries=["test retrieval query"],
    )
    choice = MagicMock()
    choice.message.parsed = parsed
    response = MagicMock()
    response.choices = [choice]
    return response


class QueryIntentClassifierTests(unittest.IsolatedAsyncioTestCase):
    async def _classify(self, question: str, intent: QueryIntent) -> QueryIntentResult:
        mock_client = AsyncMock()
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_parse_response(intent),
        )
        with patch("app.services.query_intent.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.chat_model = "gpt-4o-mini"
            mock_settings.debug_mode = False
            return await classify_query_intent(question, client=mock_client)

    async def test_structured_output_course_info(self):
        result = await self._classify("When is the final exam?", QueryIntent.COURSE_INFO)
        self.assertEqual(result.intent, QueryIntent.COURSE_INFO)
        self.assertTrue(result.search_queries)

    async def test_structured_output_learning(self):
        result = await self._classify("What is a project manager?", QueryIntent.LEARNING)
        self.assertEqual(result.intent, QueryIntent.LEARNING)

    async def test_structured_output_assignment(self):
        result = await self._classify("What do I submit for HW3?", QueryIntent.ASSIGNMENT)
        self.assertEqual(result.intent, QueryIntent.ASSIGNMENT)

    async def test_structured_output_mixed(self):
        result = await self._classify(
            "What topics from Chapter 7 will be on the final?",
            QueryIntent.MIXED,
        )
        self.assertEqual(result.intent, QueryIntent.MIXED)

    async def test_no_api_key_fallback(self):
        with patch("app.services.query_intent.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            mock_settings.debug_mode = False
            result = await plan_query("What is a system?")
        self.assertEqual(result.intent, QueryIntent.LEARNING)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.search_queries, ["What is a system?"])

    async def test_debug_logging(self):
        mock_client = AsyncMock()
        mock_client.beta.chat.completions.parse = AsyncMock(
            return_value=_mock_parse_response(QueryIntent.LEARNING, 0.88),
        )
        with patch("app.services.query_intent.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.chat_model = "gpt-4o-mini"
            mock_settings.debug_mode = True
            with patch("app.services.query_intent.logger") as mock_logger:
                await plan_query("What is a system?", client=mock_client)
                mock_logger.info.assert_called_once()
                args = mock_logger.info.call_args[0]
                self.assertIn("QUESTION:", args[0])
                self.assertIn("SEARCH_QUERIES:", args[0])
                self.assertIn("What is a system?", args[1])


class CourseWidePolicyQuestionTests(unittest.TestCase):
    def test_homework_weight_is_course_policy(self):
        from app.services.query_intent import is_course_wide_policy_question

        self.assertTrue(is_course_wide_policy_question("作业占比总成绩百分之多少"))
        self.assertTrue(is_course_wide_policy_question("这个课作业占整个 grade 的多少？"))
        self.assertTrue(is_course_wide_policy_question("How much is homework worth?"))
        self.assertTrue(is_course_wide_policy_question("What percent of the grade are assignments?"))

    def test_named_hw_policy_is_not_course_wide(self):
        from app.services.query_intent import is_course_wide_policy_question

        self.assertFalse(is_course_wide_policy_question("What's the late penalty for Homework 2?"))
        self.assertFalse(is_course_wide_policy_question("HW3是啥"))
        self.assertFalse(is_course_wide_policy_question("What is a system?"))


if __name__ == "__main__":
    unittest.main()
