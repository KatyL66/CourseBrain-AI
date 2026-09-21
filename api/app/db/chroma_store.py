import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

import chromadb

from app.config import settings
from app.models.schemas import (
    AssignmentAttachmentIngest,
    AssignmentIngest,
    CourseResponse,
    IngestBatchRequest,
    IngestBatchResponse,
    SearchResult,
    SourceMetadata,
    TopicIngest,
)
from app.db.object_store import AssignmentObject, assignment_topic_id, load_assignments, save_assignments
from app.services.assignment_query import assignment_identifier_key
from app.services.chunker import chunk_text, strip_html
from app.services.content_classifier import classify_document
from app.services.content_filter import filter_page_texts, is_navigation_boilerplate
from app.services.embedder import embed_query, embed_texts
from app.services.parser import parse_pdf_base64

logger = logging.getLogger("coursebrain")
T = TypeVar("T")

DATA_DIR = Path(settings.data_dir)
COURSES_FILE = DATA_DIR / "courses.json"
CHROMA_DIR = DATA_DIR / "chroma"

_client: chromadb.ClientAPI | None = None


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    _ensure_dirs()
    if not COURSES_FILE.exists():
        COURSES_FILE.write_text("{}")


def is_hnsw_missing_on_disk(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "hnsw" in text and "nothing found on disk" in text


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _ensure_dirs()
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def reset_client() -> None:
    global _client
    _client = None


def _recreate_collection(course_id: str) -> None:
    name = _collection_name(course_id)
    client = get_client()
    try:
        client.delete_collection(name)
    except Exception:
        logger.warning("could not delete broken chroma collection %s", name)
    reset_client()


def _with_collection(course_id: str, op: Callable[[Any], T]) -> T:
    """Run a collection operation; recreate the persistent client once on failure."""
    try:
        return op(_get_collection(course_id))
    except Exception as exc:
        logger.exception("chroma operation failed; resetting persistent client")
        reset_client()
        try:
            return op(_get_collection(course_id))
        except Exception as retry_exc:
            if is_hnsw_missing_on_disk(exc) or is_hnsw_missing_on_disk(retry_exc):
                logger.error("chroma hnsw missing on disk; leaving collection for re-sync")
            raise retry_exc


def _readable_collection(course_id: str):
    """Return a collection, recreating it if the HNSW index files are gone."""
    coll = _get_collection(course_id)
    try:
        if coll.count() == 0:
            return coll
        coll.peek(limit=1)
        return coll
    except Exception as exc:
        if not is_hnsw_missing_on_disk(exc):
            raise
        logger.warning("recreating chroma collection after hnsw missing-on-disk course_id=%s", course_id)
        _recreate_collection(course_id)
        return _get_collection(course_id)


def _load_courses() -> dict:
    init_db()
    return json.loads(COURSES_FILE.read_text())


def _save_courses(courses: dict) -> None:
    _ensure_dirs()
    COURSES_FILE.write_text(json.dumps(courses, indent=2, default=str))


def _collection_name(course_id: str) -> str:
    return f"course_{course_id}"


def _get_collection(course_id: str):
    return get_client().get_or_create_collection(
        name=_collection_name(course_id),
        metadata={"hnsw:space": "cosine"},
    )


def get_or_create_course(external_id: str, name: str, platform: str) -> dict:
    courses = _load_courses()
    if external_id in courses:
        courses[external_id]["name"] = name
        _save_courses(courses)
        return courses[external_id]

    course = {
        "id": str(uuid.uuid4()),
        "external_id": external_id,
        "name": name,
        "platform": platform,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    courses[external_id] = course
    _save_courses(courses)
    return course


def find_course_by_external_id(external_id: str) -> dict | None:
    return _load_courses().get(external_id)


def find_course_by_id(course_id: UUID) -> dict | None:
    cid = str(course_id)
    for course in _load_courses().values():
        if course["id"] == cid:
            return course
    return None


def get_course_stats(course_id: UUID) -> CourseResponse | None:
    course = find_course_by_id(course_id)
    if not course:
        return None

    collection = _get_collection(course["id"])
    chunk_count = collection.count()
    topic_ids = set()
    if chunk_count:
        data = collection.get(include=["metadatas"])
        for meta in data.get("metadatas") or []:
            if meta and meta.get("topic_external_id"):
                topic_ids.add(meta["topic_external_id"])

    return CourseResponse(
        id=UUID(course["id"]),
        external_id=course["external_id"],
        name=course["name"],
        platform=course["platform"],
        topic_count=len(topic_ids),
        chunk_count=chunk_count,
        created_at=datetime.fromisoformat(course["created_at"]),
    )


def list_all_courses() -> list[CourseResponse]:
    courses = _load_courses()
    result: list[CourseResponse] = []
    for course in courses.values():
        stats = get_course_stats(UUID(course["id"]))
        if stats:
            result.append(stats)
    result.sort(key=lambda c: c.created_at, reverse=True)
    return result


def _extract_page_chunks(topic_data: TopicIngest) -> list[tuple[int | None, str]]:
    if topic_data.content_base64:
        pages = parse_pdf_base64(topic_data.content_base64)
    elif topic_data.content:
        text = strip_html(topic_data.content) if "<" in topic_data.content else topic_data.content
        pages = [(None, text)]
    else:
        return []

    return filter_page_texts(pages)


def _delete_topic_chunks(collection, topic_external_id: str) -> None:
    existing = collection.get(where={"topic_external_id": topic_external_id})
    if existing["ids"]:
        collection.delete(ids=existing["ids"])


async def ingest_batch(payload: IngestBatchRequest) -> IngestBatchResponse:
    course = get_or_create_course(payload.external_id, payload.name, payload.platform)
    collection = _readable_collection(course["id"])

    indexed = 0
    total_chunks = 0
    skipped: list[str] = []

    for topic_data in payload.topics:
        page_chunks = _extract_page_chunks(topic_data)
        if not page_chunks:
            skipped.append(topic_data.title)
            logger.info("ingest skip title=%s reason=empty_parse file_type=%s", topic_data.title, topic_data.file_type)
            continue

        all_texts: list[str] = []
        chunk_meta: list[tuple[int | None, str]] = []
        for page, page_text in page_chunks:
            for part in chunk_text(page_text):
                if is_navigation_boilerplate(part.text):
                    continue
                all_texts.append(part.text)
                chunk_meta.append((page, part.text[:120]))

        if not all_texts:
            skipped.append(topic_data.title)
            logger.info("ingest skip title=%s reason=empty_chunks", topic_data.title)
            continue

        embeddings = await embed_texts(all_texts)
        _delete_topic_chunks(collection, topic_data.external_id)

        content_type = classify_document(topic_data, body="\n".join(all_texts)).value

        ids = []
        metadatas = []
        for idx, (text_part, (page, anchor)) in enumerate(zip(all_texts, chunk_meta)):
            chunk_id = str(uuid.uuid4())
            ids.append(chunk_id)
            meta = {
                "topic_external_id": topic_data.external_id,
                "topic_title": topic_data.title,
                "module_name": topic_data.module_name or "",
                "content_type": content_type,
                "source_type": "content",
                "url": topic_data.url,
                "file_type": topic_data.file_type or "",
                "anchor_text": anchor or "",
            }
            if page is not None:
                meta["page"] = page
            metadatas.append(meta)

        collection.add(
            ids=ids,
            documents=all_texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        total_chunks += len(all_texts)
        indexed += 1

    indexed_assignments, assignment_chunks = await _ingest_assignments(
        collection, UUID(course["id"]), payload.assignments, skipped,
    )
    total_chunks += assignment_chunks

    return IngestBatchResponse(
        course_id=UUID(course["id"]),
        indexed_topics=indexed,
        total_chunks=total_chunks,
        skipped=skipped,
        indexed_assignments=indexed_assignments,
    )


def _attachment_is_pdf(attachment: AssignmentAttachmentIngest) -> bool:
    filename = str(getattr(attachment, "filename", "") or "").lower()
    file_type = str(getattr(attachment, "file_type", "") or "").lower()
    return file_type == "pdf" or filename.endswith(".pdf")


def _assignment_page_texts(assignment: AssignmentIngest) -> list[tuple[int | None, str]]:
    pages: list[tuple[int | None, str]] = []
    if assignment.instructions:
        text = (
            strip_html(assignment.instructions)
            if "<" in assignment.instructions
            else assignment.instructions
        )
        pages.append((None, text))
    names = [item.filename for item in assignment.attachments if item.filename]
    if names:
        pages.append((None, "Attachments: " + ", ".join(names)))
    for idx, attachment in enumerate(assignment.attachments, start=1):
        if attachment.content_base64 and _attachment_is_pdf(attachment):
            pages.extend(parse_pdf_base64(attachment.content_base64))
        elif attachment.content:
            text = strip_html(attachment.content) if "<" in attachment.content else attachment.content
            pages.append((idx, text))
    return filter_page_texts(pages)


async def _embed_assignment_text(collection, assignment: AssignmentIngest, obj: AssignmentObject) -> int:
    topic_id = assignment_topic_id(obj.object_id)
    page_chunks = _assignment_page_texts(assignment)
    all_texts: list[str] = []
    chunk_meta: list[tuple[int | None, str]] = []
    for page, page_text in page_chunks:
        for part in chunk_text(page_text):
            if is_navigation_boilerplate(part.text):
                continue
            all_texts.append(part.text)
            chunk_meta.append((page, part.text[:120]))

    _delete_topic_chunks(collection, topic_id)
    if not all_texts:
        return 0

    embeddings = await embed_texts(all_texts)
    ids = []
    metadatas = []
    for text_part, (page, anchor) in zip(all_texts, chunk_meta):
        ids.append(str(uuid.uuid4()))
        meta = {
            "topic_external_id": topic_id,
            "topic_title": obj.name,
            "module_name": "Assignments",
            "content_type": "assignment",
            "source_type": "assignment",
            "object_id": obj.object_id,
            "identifier": obj.identifier or "",
            "url": obj.canonical_url,
            "file_type": "",
            "anchor_text": anchor or "",
        }
        if page is not None:
            meta["page"] = page
        metadatas.append(meta)
    collection.add(
        ids=ids,
        documents=all_texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(all_texts)


async def _ingest_assignments(
    collection,
    course_id: UUID,
    assignments: list[AssignmentIngest],
    skipped: list[str],
) -> tuple[int, int]:
    old_ids = {item.object_id for item in load_assignments(course_id)}
    stored: list[AssignmentObject] = []
    kept_payloads: list[tuple[AssignmentIngest, AssignmentObject]] = []

    for assignment in assignments:
        if not assignment.object_id or not assignment.name:
            skipped.append(assignment.name or assignment.object_id or "assignment")
            continue

        obj = AssignmentObject(
            object_id=assignment.object_id,
            name=assignment.name,
            canonical_url=assignment.canonical_url,
            identifier=assignment_identifier_key(assignment.name),
            due_at=assignment.due_at,
            submission_type=assignment.submission_type,
        )
        stored.append(obj)
        kept_payloads.append((assignment, obj))

    save_assignments(course_id, stored)

    chunk_count = 0
    for assignment, obj in kept_payloads:
        try:
            chunk_count += await _embed_assignment_text(collection, assignment, obj)
        except Exception:
            logger.exception("assignment text ingest failed object_id=%s", obj.object_id)
            skipped.append(obj.name)

    kept = {item.object_id for item in stored}
    for removed_id in old_ids - kept:
        _delete_topic_chunks(collection, assignment_topic_id(removed_id))
    return len(stored), chunk_count


def _build_query_where(
    content_types: list[str] | None,
    topic_external_id: str | None,
) -> dict | None:
    clauses: list[dict] = []
    if content_types:
        if len(content_types) == 1:
            clauses.append({"content_type": content_types[0]})
        else:
            clauses.append({"content_type": {"$in": content_types}})
    if topic_external_id:
        clauses.append({"topic_external_id": topic_external_id})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


async def query_chunks(
    course_id: UUID,
    query: str,
    content_types: list[str] | None = None,
    n_results: int = 10,
    *,
    topic_external_id: str | None = None,
) -> list[SearchResult]:
    """Vector search with optional content_type / topic filters. rank is unset (0)."""
    course = find_course_by_id(course_id)
    if not course:
        return []

    try:
        collection = _get_collection(course["id"])
        if collection.count() == 0:
            return []
    except Exception as exc:
        if is_hnsw_missing_on_disk(exc):
            logger.exception("chroma count skipped; hnsw index missing on disk")
            return []
        raise

    query_vec = await embed_query(query)
    n_results = min(n_results, collection.count())
    where = _build_query_where(content_types, topic_external_id)

    def _do_query(coll):
        query_kwargs: dict = {
            "query_embeddings": [query_vec],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_kwargs["where"] = where
        try:
            return coll.query(**query_kwargs)
        except Exception:
            return coll.query(
                query_embeddings=[query_vec],
                n_results=n_results,
                include=["documents", "metadatas", "distances"],
            )

    try:
        results = _with_collection(course["id"], _do_query)
    except Exception as exc:
        if is_hnsw_missing_on_disk(exc):
            logger.exception("chroma query skipped; hnsw index missing on disk")
            return []
        raise
    return _parse_query_results(course_id, results)


async def search_chunks(course_id: UUID, query: str, top_k: int = 5) -> list[SearchResult]:
    """Unfiltered semantic search (legacy). Prefer routed_search for chat."""
    hits = await query_chunks(course_id, query, None, n_results=top_k)
    return _assign_result_ranks(hits)


def _assign_result_ranks(hits: list[SearchResult]) -> list[SearchResult]:
    return [h.model_copy(update={"rank": i}) for i, h in enumerate(hits, start=1)]


def _parse_query_results(course_id: UUID, results: dict) -> list[SearchResult]:
    hits: list[SearchResult] = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]

    for chunk_id, text, meta, dist in zip(ids, docs, metas, dists):
        page = meta.get("page")
        if isinstance(page, float):
            page = int(page)
        distance = float(dist)
        source = SourceMetadata(
            course_id=str(course_id),
            module=meta.get("module_name") or None,
            content_type=meta.get("content_type") or None,
            topic_id=meta.get("topic_external_id", ""),
            topic_title=meta.get("topic_title", ""),
            url=meta.get("url", ""),
            file_type=meta.get("file_type") or None,
            page=page,
            anchor_text=meta.get("anchor_text") or None,
            source_type=meta.get("source_type") or None,
        )
        hits.append(SearchResult(
            chunk_id=UUID(chunk_id),
            rank=0,
            text=text,
            score=1 - distance,
            distance=distance,
            source=source,
        ))
    return hits
