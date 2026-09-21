import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.db import chroma_store
from app.main import app


class StagingApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig_paths = (
            chroma_store.DATA_DIR,
            chroma_store.COURSES_FILE,
            chroma_store.CHROMA_DIR,
            chroma_store._client,
        )
        chroma_store.DATA_DIR = self.tmp
        chroma_store.COURSES_FILE = self.tmp / "courses.json"
        chroma_store.CHROMA_DIR = self.tmp / "chroma"
        chroma_store._client = None
        self._orig_key = settings.coursebrain_api_key
        settings.coursebrain_api_key = ""

    def tearDown(self):
        settings.coursebrain_api_key = self._orig_key
        (
            chroma_store.DATA_DIR,
            chroma_store.COURSES_FILE,
            chroma_store.CHROMA_DIR,
            chroma_store._client,
        ) = self._orig_paths

    def test_health_is_public_and_returns_request_id(self):
        with TestClient(app) as client:
            res = client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")
        self.assertTrue(res.headers.get("X-Request-ID"))

    def test_courses_open_when_api_key_unset(self):
        with TestClient(app) as client:
            res = client.get("/api/v1/courses")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["courses"], [])

    def test_api_key_rejects_missing_header(self):
        settings.coursebrain_api_key = "staging-secret"
        with TestClient(app) as client:
            res = client.get("/api/v1/courses")
        self.assertEqual(res.status_code, 401)

    def test_health_stays_public_when_api_key_set(self):
        settings.coursebrain_api_key = "staging-secret"
        with TestClient(app) as client:
            res = client.get("/health")
        self.assertEqual(res.status_code, 200)

    def test_api_key_accepts_matching_header(self):
        settings.coursebrain_api_key = "staging-secret"
        with TestClient(app) as client:
            res = client.get(
                "/api/v1/courses",
                headers={"X-CourseBrain-Key": "staging-secret"},
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["courses"], [])

    def test_cors_preflight_is_public(self):
        settings.coursebrain_api_key = "staging-secret"
        with TestClient(app) as client:
            res = client.options(
                "/api/v1/chat",
                headers={
                    "Origin": "chrome-extension://abc",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type,x-coursebrain-key",
                },
            )
        self.assertNotEqual(res.status_code, 401)
        self.assertLess(res.status_code, 400)

    def test_unhandled_exception_returns_json_500(self):
        from unittest.mock import patch
        from uuid import uuid4

        async def boom(*_args, **_kwargs):
            raise RuntimeError("chroma exploded")

        with patch("app.routers.chat.chat_with_rag", side_effect=boom):
            with TestClient(app, raise_server_exceptions=False) as client:
                res = client.post(
                    "/api/v1/chat",
                    json={"course_id": str(uuid4()), "message": "hw1是啥"},
                )
        self.assertEqual(res.status_code, 500)
        body = res.json()
        self.assertIn("chroma exploded", body["detail"])
        self.assertTrue(res.headers.get("X-Request-ID"))
