import logging

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.schemas import ChatRequest, ChatResponse, Citation, SourceReference
from app.request_context import request_id_ctx
from app.services.rag import chat_with_rag

logger = logging.getLogger("coursebrain")

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _refs_to_citations(refs: list[SourceReference]) -> list[Citation]:
    return [
        Citation(
            rank=r.rank,
            topic_title=r.title,
            module=r.module,
            page=r.page,
            url=r.url,
            excerpt=r.excerpt,
        )
        for r in refs
    ]


def _to_chat_response(
    answer,
    intent,
    all_refs: list[SourceReference],
    cited_refs: list[SourceReference],
    retrieved: list[Citation],
    debug_info,
) -> ChatResponse:
    return ChatResponse(
        answer=answer,
        query_intent=intent.intent.value,
        query_intent_confidence=intent.confidence,
        references=all_refs,
        referenced=_refs_to_citations(cited_refs),
        retrieved=retrieved,
        debug=debug_info,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatRequest,
    debug: bool = Query(False, description="Include RAG pipeline debug info (requires DEBUG_MODE)"),
):
    include_debug = debug and settings.debug_mode
    request_id = request_id_ctx.get()
    logger.info(
        "chat start request_id=%s course_id=%s message=%s",
        request_id,
        payload.course_id,
        payload.message[:200],
    )
    try:
        answer, intent, cited_refs, all_refs, retrieved, debug_info = await chat_with_rag(
            payload.course_id,
            payload.message,
            include_debug=include_debug,
        )
    except ValueError as e:
        logger.warning(
            "chat rejected request_id=%s course_id=%s error=%s",
            request_id,
            payload.course_id,
            e,
        )
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(
        "chat done request_id=%s course_id=%s intent=%s refs=%s cited=%s",
        request_id,
        payload.course_id,
        intent.intent.value,
        len(all_refs),
        len(cited_refs),
    )
    return _to_chat_response(answer, intent, all_refs, cited_refs, retrieved, debug_info)


@router.post("/debug/chat", response_model=ChatResponse)
async def debug_chat_endpoint(payload: ChatRequest):
    if not settings.debug_mode:
        raise HTTPException(status_code=403, detail="Debug chat requires DEBUG_MODE=true")

    try:
        answer, intent, cited_refs, all_refs, retrieved, debug_info = await chat_with_rag(
            payload.course_id,
            payload.message,
            include_debug=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_chat_response(answer, intent, all_refs, cited_refs, retrieved, debug_info)
