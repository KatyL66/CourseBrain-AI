import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.request_context import request_id_ctx

logger = logging.getLogger("coursebrain")

_PUBLIC_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def _is_public(request: Request) -> bool:
    if request.method == "OPTIONS":
        return True
    return request.url.path in _PUBLIC_PATHS


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        try:
            if not _is_public(request):
                expected = settings.coursebrain_api_key
                if expected and request.headers.get("X-CourseBrain-Key") != expected:
                    logger.warning(
                        "unauthorized request_id=%s method=%s path=%s",
                        request_id,
                        request.method,
                        request.url.path,
                    )
                    return JSONResponse(
                        {"detail": "Unauthorized"},
                        status_code=401,
                        headers={"X-Request-ID": request_id},
                    )

            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                logger.exception(
                    "unhandled request_id=%s method=%s path=%s duration_ms=%s",
                    request_id,
                    request.method,
                    request.url.path,
                    duration_ms,
                )
                return JSONResponse(
                    {"detail": f"{type(exc).__name__}: {exc}"},
                    status_code=500,
                    headers={"X-Request-ID": request_id},
                )

            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "request_id=%s method=%s path=%s status=%s duration_ms=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)
