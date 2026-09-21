import re

from openai import AsyncOpenAI

from app.config import settings
from app.db.chroma_store import query_chunks
from app.db.object_store import assignment_topic_id
from app.models.schemas import Citation, RagDebugInfo, SearchResult, SourceReference
from app.services.assignment_query import (
    AssignmentAspect,
    AssignmentLookupStatus,
    assignment_citation,
    assignment_source_reference,
    classify_assignment_aspect,
    format_due_at,
    lookup_named_assignment,
    named_assignment_content_fallback_note,
    structured_assignment_answer,
)
from app.services.content_filter import strip_availability_chrome
from app.services.identifier_match import collect_query_identifiers, text_matches_any_identifier
from app.services.grade_policy import (
    COURSE_WIDE_POLICY_SCOPE_NOTE,
    missing_course_policy_message,
    select_course_level_policy_hits,
)
from app.services.query_intent import (
    QueryIntentResult,
    QuestionType,
    is_course_wide_policy_question,
    plan_query,
)
from app.services.retrieval_router import FINAL_TOP_K, planned_retrieval

SYSTEM_PROMPT = """You are CourseBrain — a teaching assistant who has carefully read the student's synced course materials.

Your job is NOT to be a generic chatbot or document summarizer.
Behave like a capable TA who helps the student understand what the professor/course actually says.

Priority order:
COURSE MATERIAL → faithful representation → teaching-oriented synthesis
NOT: generic AI knowledge → answer → attach sources afterward.

You receive COURSE CONTEXT blocks labeled [SOURCE N] with file, page, module, and content.
You may receive a QUERY PLAN with question type and intended coverage.
URLs are NOT provided — never invent links or URLs.

==================================================
TWO-LAYER ANSWER (keep distinct mentally)
==================================================

Layer 1 — Course-grounded facts (be faithful):
- What does the professor/course material explicitly say?
- Present authoritative content in SOURCE ORIGINAL LANGUAGE (see SOURCE LANGUAGE PRESERVATION).
- If the course gives multiple definitions, present each with original wording — do not collapse into one generic definition.
- Only call something a "definition of X" if the source actually defines X.
  (A definition of "systems engineering" is NOT a definition of "system".)
- If a slide label says "Definition (Dr. Simon Ramo)" but the quoted text defines
  "systems engineering", present it as related context about systems engineering —
  NOT as another definition of "system".
- Never invent professor statements, course examples, dates, policies, or requirements.

Layer 2 — Teaching synthesis (help the student understand):
- After presenting course material, explain what it means in plain language.
- Synthesize: what do the definitions share? What is the professor emphasizing? Why does it matter?
- For concept questions, reasonably include related retrieved evidence (characteristics, emergent behavior, examples) when it materially helps understanding — but do not turn every answer into a full lecture.
- General knowledge may clarify or analogize, but must not contradict the course or be presented as something the professor said.

==================================================
SOURCE LANGUAGE PRESERVATION (global rule)
==================================================

CourseBrain must distinguish two language domains:

1. AUTHORITATIVE COURSE CONTENT — preserve SOURCE ORIGINAL LANGUAGE
2. AI TEACHING / EXPLANATION — use USER LANGUAGE

These are INDEPENDENT variables:
- User language → controls explanation / synthesis / 人话解释
- Source language → controls definitions, terminology, formulas, quoted requirements

Do NOT translate the entire answer into the user's language.
Do NOT assume "user asks in Chinese → everything in Chinese."

--------------------------------
A. AUTHORITATIVE COURSE CONTENT
--------------------------------

When presenting content from the course whose original wording matters for
learning, studying, memorization, or exams, preserve the ORIGINAL LANGUAGE
from the course material.

This applies to:
- definitions
- formal statements
- terminology and concept names
- theorem / framework / method names
- formulas and formula names
- professor-specific wording
- quoted assignment requirements
- official course terminology

Format each important definition as:

Original definition:
"[exact or faithful wording from course material in its original language]"

人话解释: (if user asks in Chinese)
[user-language plain explanation]

Or in English if the user asked in English:
Plain-language explanation: ...

NEVER present an AI translation or paraphrase as if it were the original
course definition. Never translate away a definition into the user's language
in place of the original.

BAD (user asks in Chinese, course is English):
  Oxford English Dictionary: "系统是一组相互连接的事物……"

GOOD:
  Oxford English Dictionary (1933):
  Original definition:
  "A set or assemblage of things connected, associated, or interdependent,
  so as to form a complex unity..."
  人话解释：system 不是简单把很多东西放在一起，而是这些部分彼此连接、
  关联或相互依赖，从而形成一个整体。

If exact original wording is in COURSE CONTEXT, quote it faithfully.
If only partial/uncertain passage is available, do not reconstruct or invent quotes.

--------------------------------
B. TEACHING / EXPLANATION
--------------------------------

AI-generated explanation follows the USER'S LANGUAGE:
- course material English + user Chinese → original English + 中文讲解
- course material English + user English → English throughout (including framing and synthesis)
- Teaching synthesis, clarifications, examples explanation → user language

--------------------------------
C. PRESERVE COURSE TERMINOLOGY
--------------------------------

Important course terminology keeps its original form alongside user-language help:

  emergent behavior（涌现行为）
  Critical Path Method (CPM)
  system
  Newton's Method

Do not replace original terminology entirely with translation.
Students need to recognize terms from lectures, assignments, and exams.

--------------------------------
D. APPLY GENERALLY
--------------------------------

This rule applies to ALL topics — not just "system":
- "What is CPM?" → CPM + original English definition + Chinese 人话解释
- "What is Newton's method?" → preserve method name/formula + explain in user language
- "What does the professor define X as?" → original definition first, then explanation

==================================================
PRESENTATION STYLE
==================================================

Adapt structure to the question — do NOT force one rigid template.

Good concept-explanation flow (omit sections that do not help):
1. Direct answer / framing ("根据 Week 1 课件，教授从几个角度解释了 system...")
2. What the course says — each definition: Original definition (source language) + 人话解释 (user language)
3. Key synthesis — what the professor is really emphasizing (user language)
4. Course examples from lecture (prefer professor's examples; names in original language when relevant)
5. Short takeaway (user language)

For narrow questions, stay narrow:
- factual_lookup → concise factual answer only
- definition → original definition(s) in source language + brief 人话解释
- example → focus on course examples
- assignment_help → direct assignment answer

==================================================
CITATIONS (critical)
==================================================

When citing course material inline, use ONLY this format:
  [SOURCE N]

Examples:
  根据 [SOURCE 1]，教授给出了……
  Rechtin 的定义是…… [SOURCE 5]

Rules:
- N must match a [SOURCE N] block in COURSE CONTEXT.
- Do NOT invent source numbers.
- Do NOT output URLs, markdown links, or fabricated page references.
- Cite sources for important course-derived claims.

==================================================
NAMED IDENTIFIER GROUNDING (critical)
==================================================

When the student asks about a SPECIFIC named or numbered object, such as:
HW1, HW 1, Homework 1, Project 2, Quiz 3, Midterm, Chapter 4, Week 6, etc.

You MUST prefer evidence that EXPLICITLY mentions that same identifier.

Priority:
  explicit identifier match  >  generic related evidence

Example — student asks "HW1 是什么":
  Evidence A: "There will be a team project..."
  Evidence B: "HW 1: 1-page written summary of key points learned from EPM chapter 1..."
  → Use Evidence B. Do NOT infer team project = HW1.

Rules:
- Do NOT merge different course objects unless the materials explicitly link them.
- Generic assignment/project language does NOT automatically answer a numbered HW/Quiz/Project question.
- If a [SOURCE N] block is marked "Explicit identifier match: yes", treat it as primary evidence.
- If explicit-identifier evidence exists, base your answer on it — not on loosely related project/assignment chunks.
- If no explicit-identifier evidence exists, say the synced materials do not clearly specify that item.

==================================================
WHEN EVIDENCE IS INSUFFICIENT
==================================================

If retrieved course materials do not support a course-specific claim, say clearly that the currently synced course materials do not provide enough information. Do not guess.

==================================================
COURSE-LEVEL GRADING vs ASSIGNMENT/PROJECT RUBRICS
==================================================

When the student asks what share of the COURSE GRADE is homework, exams, etc.:
- Use only evidence that describes course-wide grade composition (syllabus, overview grading scheme, total/final grade weights).
- Do NOT treat assignment or project INTERNAL scores as the course grade
  (Peer Review 15 points, Report Part I, Partner Evaluation, rubric points inside one deliverable).
- If no course-level breakdown is in COURSE CONTEXT, say so. Do not infer one.

==================================================
CONTENT AVAILABILITY IS NOT A DUE DATE
==================================================

Brightspace phrases like "Starts …", "Ends …", and "Available until …" describe when content is visible, not when homework is due. Never present them as assignment deadlines.

==================================================
EFFICIENCY
==================================================

Retrieved chunks are evidence, not a paragraph checklist.
Combine overlapping chunks. Ignore irrelevant ones. Write for the student's question."""

_SOURCE_REF_RE = re.compile(r"\[SOURCE\s+(\d+)(?:[^\]]*)?\]", re.IGNORECASE)


def _build_source_label(hit: SearchResult) -> str:
    parts: list[str] = []
    if hit.source.module:
        module = hit.source.module.split(">")[-1].strip()
        if module:
            parts.append(module)
    elif hit.source.topic_title:
        parts.append(hit.source.topic_title)
    if hit.source.page is not None:
        parts.append(f"Slide {hit.source.page}")
    return " · ".join(parts) if parts else (hit.source.topic_title or "Course material")


def format_rag_context(hits: list[SearchResult], query_identifiers: list | None = None) -> str:
    """Format context for LLM — no URLs (frontend/backend control links)."""
    blocks: list[str] = []
    for hit in hits:
        text = strip_availability_chrome(hit.text)
        if not text:
            continue
        page = str(hit.source.page) if hit.source.page is not None else "n/a"
        module = hit.source.module or "n/a"
        content_type = hit.source.content_type or "n/a"
        label = _build_source_label(hit)
        id_match = ""
        if query_identifiers and text_matches_any_identifier(hit.text, query_identifiers):
            id_match = "Explicit identifier match: yes\n"
        blocks.append(
            f"[SOURCE {hit.rank}]\n"
            f"{id_match}"
            f"Label: {label}\n"
            f"File: {hit.source.topic_title}\n"
            f"Page: {page}\n"
            f"Content type: {content_type}\n"
            f"Module: {module}\n"
            f"Content:\n{text}"
        )
    return "\n\n".join(blocks)


def reorder_hits_by_identifier_match(
    hits: list[SearchResult],
    query_identifiers: list,
) -> list[SearchResult]:
    """Put explicitly matching chunks first so generation sees primary evidence early."""
    if not query_identifiers:
        return hits

    matched: list[SearchResult] = []
    other: list[SearchResult] = []
    for hit in hits:
        if text_matches_any_identifier(hit.text, query_identifiers):
            matched.append(hit)
        else:
            other.append(hit)

    reordered = matched + other
    return [hit.model_copy(update={"rank": i}) for i, hit in enumerate(reordered, start=1)]


def _generation_directive(plan: QueryIntentResult) -> str:
    directives: dict[QuestionType, str] = {
        QuestionType.FACTUAL_LOOKUP: "Answer the specific fact concisely. Do not expand.",
        QuestionType.DEFINITION: (
            "Present original course definition(s) in source language, then 人话解释 in user language."
        ),
        QuestionType.CONCEPT_EXPLANATION: (
            "Faithful course content + teaching synthesis. "
            "Cover definitions, key idea, and course examples when retrieved."
        ),
        QuestionType.EXAMPLE: "Focus on examples given in the course materials.",
        QuestionType.COMPARISON: "Compare using course evidence; highlight key differences.",
        QuestionType.PROCEDURE: "Explain when/how based on course material.",
        QuestionType.ASSIGNMENT_HELP: (
            "Answer directly from evidence that explicitly names the requested assignment/item. "
            "Do not substitute a different project/homework unless materials explicitly equate them."
        ),
        QuestionType.OTHER: "Answer directly using retrieved course evidence.",
    }
    return directives.get(plan.question_type, directives[QuestionType.OTHER])


def build_chat_messages(
    question: str,
    context: str,
    plan: QueryIntentResult | None = None,
    extra_note: str | None = None,
) -> list[dict[str, str]]:
    plan_block = ""
    if plan:
        directive = _generation_directive(plan)
        plan_block = (
            f"\n\nQUERY PLAN:\n"
            f"  Question type: {plan.question_type.value}\n"
            f"  Topic: {plan.topic or 'n/a'}\n"
            f"  Teaching directive: {directive}"
        )
        if plan.search_queries:
            queries = "\n".join(f"  - {q}" for q in plan.search_queries)
            plan_block += f"\n  Intended coverage:\n{queries}"
    if extra_note:
        plan_block += f"\n\n{extra_note}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "COURSE CONTEXT (retrieved from synced course materials):\n\n"
                f"{context}"
                f"{plan_block}\n\n"
                f"STUDENT QUESTION:\n{question}"
            ),
        },
    ]


def hits_to_source_references(hits: list[SearchResult]) -> list[SourceReference]:
    refs: list[SourceReference] = []
    for hit in hits:
        rank = hit.rank or 0
        refs.append(
            SourceReference(
                id=f"source_{rank}",
                rank=rank,
                title=hit.source.topic_title,
                module=hit.source.module,
                page=hit.source.page,
                url=hit.source.url,
                content_type=hit.source.content_type,
                label=_build_source_label(hit),
                excerpt=hit.text[:240],
            ),
        )
    return refs


def hits_to_citations(hits: list[SearchResult]) -> list[Citation]:
    return [
        Citation(
            rank=h.rank,
            score=h.score,
            topic_title=h.source.topic_title,
            module=h.source.module,
            page=h.source.page,
            url=h.source.url,
            excerpt=h.text[:240],
        )
        for h in hits
    ]


def extract_referenced_sources(
    answer: str,
    all_refs: list[SourceReference],
) -> list[SourceReference]:
    ranks = {int(m.group(1)) for m in _SOURCE_REF_RE.finditer(answer)}
    if not ranks:
        return all_refs[:3]

    by_rank = {r.rank: r for r in all_refs}
    referenced = [by_rank[r] for r in sorted(ranks) if r in by_rank]
    return referenced or all_refs[:3]


def extract_referenced_citations(answer: str, all_citations: list[Citation]) -> list[Citation]:
    ranks = {int(m.group(1)) for m in _SOURCE_REF_RE.finditer(answer)}
    if not ranks:
        return all_citations[:3]

    by_rank = {c.rank: c for c in all_citations if c.rank is not None}
    referenced = [by_rank[r] for r in sorted(ranks) if r in by_rank]
    return referenced or all_citations[:3]


def build_debug_info(
    question: str,
    intent: QueryIntentResult,
    hits: list[SearchResult],
    context: str,
    messages: list[dict[str, str]],
) -> RagDebugInfo:
    return RagDebugInfo(
        question=question,
        query_intent=intent.intent.value,
        query_intent_confidence=intent.confidence,
        question_type=intent.question_type.value,
        topic=intent.topic,
        search_queries=list(intent.search_queries),
        retrieval=hits,
        rag_context=context,
        messages=messages,
        model=settings.chat_model,
    )


def _assignment_object_context(obj, rank: int = 1) -> str:
    due = format_due_at(obj.due_at) if obj.due_at else "none listed in Assignments"
    submit = obj.submission_type or "unspecified"
    return (
        f"[SOURCE {rank}]\n"
        f"Label: Assignments · {obj.name}\n"
        f"File: {obj.name}\n"
        f"Page: n/a\n"
        f"Content type: assignment\n"
        f"Module: Assignments\n"
        f"Content:\n"
        f"Brightspace Assignments (dropbox) object.\n"
        f"Due date (structured): {due}\n"
        f"Submission type: {submit}\n"
        f"Open/submit in the Assignments folder (use the source link).\n"
        f"Do not use Content visibility dates as this due date."
    )


async def _assignment_instruction_hits(course_id, obj, message: str, plan: QueryIntentResult):
    queries = [message, *plan.search_queries]
    queries = [q.strip() for q in queries if q.strip()][:3]
    scoped: list[SearchResult] = []
    for query in queries:
        scoped.extend(
            await query_chunks(
                course_id,
                query,
                None,
                n_results=6,
                topic_external_id=assignment_topic_id(obj.object_id),
            ),
        )
    best: dict[str, SearchResult] = {}
    for hit in scoped:
        key = str(hit.chunk_id)
        if key not in best or hit.score > best[key].score:
            best[key] = hit
    primary = sorted(best.values(), key=lambda h: -h.score)[:6]

    secondary_raw = await query_chunks(course_id, message, None, n_results=4)
    extra: list[SearchResult] = []
    used = {str(h.chunk_id) for h in primary}
    for hit in secondary_raw:
        if (hit.source.topic_id or "").startswith("assignment:"):
            continue
        if str(hit.chunk_id) in used:
            continue
        extra.append(hit)
        if len(extra) >= 2:
            break

    ranked: list[SearchResult] = []
    for i, hit in enumerate(primary + extra, start=2):
        ranked.append(hit.model_copy(update={"rank": i}))
    return ranked


def _empty_named_assignment_message(question: str, status: AssignmentLookupStatus) -> str:
    zh = bool(re.search(r"[\u4e00-\u9fff]", question))
    if status == AssignmentLookupStatus.SOURCE_UNSYNCED:
        if zh:
            return (
                "目前没有同步到对应的 Brightspace Assignment，Content 检索也没有找到相关材料。"
                "请再同步一次课程后再问。"
            )
        return (
            "No Brightspace Assignment object is synced for this course, and Content search "
            "did not find matching material. Sync the course and try again."
        )
    if zh:
        return (
            "Brightspace Assignments 里还没有这个作业的提交文件夹，"
            "同步的课程 Content 里也没有检索到足够信息。"
        )
    return (
        "There is no matching Brightspace Assignment object, and synced Content "
        "does not contain enough information about this item."
    )


async def chat_with_rag(
    course_id,
    message: str,
    *,
    include_debug: bool = False,
) -> tuple[
    str,
    QueryIntentResult,
    list[SourceReference],
    list[SourceReference],
    list[Citation],
    RagDebugInfo | None,
]:
    plan = await plan_query(message)
    query_identifiers = collect_query_identifiers(message, *plan.search_queries)
    lookup_status, assignment = lookup_named_assignment(
        course_id, collect_query_identifiers(message),
    )
    if lookup_status == AssignmentLookupStatus.FOUND and assignment:
        aspect = classify_assignment_aspect(message)
        if aspect != AssignmentAspect.INSTRUCTIONS:
            answer = structured_assignment_answer(assignment, aspect, message)
            ref = assignment_source_reference(assignment)
            cit = assignment_citation(assignment)
            debug_info = None
            if include_debug:
                debug_info = build_debug_info(message, plan, [], answer, [])
            return answer, plan, [ref], [ref], [cit], debug_info

        hits = await _assignment_instruction_hits(course_id, assignment, message, plan)
        object_block = _assignment_object_context(assignment)
        context = object_block
        if hits:
            context = object_block + "\n\n" + format_rag_context(hits, query_identifiers)
        messages = build_chat_messages(message, context, plan)
        object_ref = assignment_source_reference(assignment, rank=1)
        all_refs = [object_ref] + hits_to_source_references(hits)
        retrieved = [assignment_citation(assignment)] + hits_to_citations(hits)
        debug_info = build_debug_info(message, plan, hits, context, messages) if include_debug else None
        if not settings.openai_api_key:
            return (
                f"(OPENAI_API_KEY not configured — showing assignment object)\n\n{object_block}",
                plan,
                [object_ref],
                all_refs,
                retrieved,
                debug_info,
            )
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.chat_model,
            messages=messages,
            temperature=0.2,
        )
        answer = response.choices[0].message.content or ""
        referenced = extract_referenced_sources(answer, all_refs)
        return answer, plan, referenced, all_refs, retrieved, debug_info

    fallback_note = None
    if lookup_status in {
        AssignmentLookupStatus.MISSING_OBJECT,
        AssignmentLookupStatus.SOURCE_UNSYNCED,
    }:
        fallback_note = named_assignment_content_fallback_note(
            classify_assignment_aspect(message),
            lookup_status,
        )

    planned = await planned_retrieval(course_id, message, plan, final_top_k=FINAL_TOP_K)
    hits = reorder_hits_by_identifier_match(planned.final_results, query_identifiers)
    if is_course_wide_policy_question(message):
        hits = select_course_level_policy_hits(hits)
        if not hits:
            empty = missing_course_policy_message(message)
            return empty, plan, [], [], [], None
        fallback_note = (
            f"{fallback_note}\n\n{COURSE_WIDE_POLICY_SCOPE_NOTE}"
            if fallback_note
            else COURSE_WIDE_POLICY_SCOPE_NOTE
        )

    if not hits:
        if lookup_status in {
            AssignmentLookupStatus.MISSING_OBJECT,
            AssignmentLookupStatus.SOURCE_UNSYNCED,
        }:
            empty = _empty_named_assignment_message(message, lookup_status)
        else:
            empty = (
                "The course materials available to CourseBrain do not contain any indexed content yet. "
                "Please sync the course first."
            )
        return empty, plan, [], [], [], None

    context = format_rag_context(hits, query_identifiers)
    messages = build_chat_messages(message, context, plan, extra_note=fallback_note)
    all_refs = hits_to_source_references(hits)
    retrieved = hits_to_citations(hits)
    debug_info = build_debug_info(message, plan, hits, context, messages) if include_debug else None

    if not settings.openai_api_key:
        excerpt = hits[0].text[:200]
        return (
            f"(OPENAI_API_KEY not configured — showing top retrieval result only)\n\n{excerpt}",
            plan,
            all_refs[:1],
            all_refs,
            retrieved,
            debug_info,
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        temperature=0.2,
    )
    answer = response.choices[0].message.content or ""
    referenced = extract_referenced_sources(answer, all_refs)
    return answer, plan, referenced, all_refs, retrieved, debug_info
