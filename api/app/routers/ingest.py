import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.request_context import request_id_ctx
from app.db.chroma_store import (
    find_course_by_external_id,
    get_course_stats,
    ingest_batch,
    list_all_courses,
)
from app.models.schemas import (
    CourseListResponse,
    CourseResponse,
    IngestBatchRequest,
    IngestBatchResponse,
)

logger = logging.getLogger("coursebrain")

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/ingest/batch", response_model=IngestBatchResponse)
async def ingest_batch_endpoint(payload: IngestBatchRequest):
    logger.info(
        "ingest start request_id=%s external_id=%s name=%s topics=%s assignments=%s",
        request_id_ctx.get(),
        payload.external_id,
        payload.name,
        len(payload.topics),
        len(payload.assignments),
    )
    result = await ingest_batch(payload)
    logger.info(
        "ingest done request_id=%s course_id=%s indexed=%s assignments=%s chunks=%s skipped=%s",
        request_id_ctx.get(),
        result.course_id,
        result.indexed_topics,
        result.indexed_assignments,
        result.total_chunks,
        len(result.skipped),
    )
    return result


@router.get("/courses", response_model=CourseListResponse)
async def list_courses():
    return CourseListResponse(courses=list_all_courses())


@router.get("/courses/{course_id}", response_model=CourseResponse)
async def get_course(course_id: UUID):
    course = get_course_stats(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/courses/by-external/{external_id}", response_model=CourseResponse)
async def get_course_by_external(external_id: str):
    course = find_course_by_external_id(external_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    stats = get_course_stats(UUID(course["id"]))
    return stats
