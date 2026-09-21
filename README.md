# CourseBrain

<p align="center">
  <img src="docs/banner.svg" alt="CourseBrain" width="100%">
</p>

CourseBrain is a Chrome-based course assistant. It indexes materials from a student's LMS, stores them in a course-specific vector collection, and answers questions from those materials with source references.

The current integration is [Brightspace](https://brightspace.usc.edu). A student opens the side panel on a course page, syncs the current course, then asks questions such as “When is Homework 1 due?” or “Where is Newton's method explained?”

This repository is a recruiting code sample. It is the real implementation, with private course data and experimental code removed.

## Problem

Course information is spread across lecture files, module pages, the syllabus, assignments, and announcements. Finding one fact often means opening several Brightspace pages.

CourseBrain turns those materials into a searchable course knowledge layer: ingest once, then ask in natural language and jump back to the source.

## Architecture

```
Student (Brightspace)
        │
        ▼
Chrome Extension
  Side Panel  ──────── chat ──────────►  FastAPI  /api/v1/chat
  Service Worker  ──── ingest ────────►  FastAPI  /api/v1/ingest/batch
  Content Script  ── session cookie ──►  Brightspace LE API
        │
        ▼
plan_query          intent + English search_queries
        │
        ├─ named assignment ──► assignment object  (due / submit / open)
        │                       or scoped retrieval (instructions)
        │
        └─ else ──► planned_retrieval
                      multi-query × intent-tier routing
                      resource resolver (HW1 / Lab2 → topic)
                      course-wide grade-policy filter
        │
        ▼
Chroma collection  course_{uuid}     +  JSON assignment objects
        │
        ▼
chat_with_rag       grounded answer + [SOURCE N]
        │
        ▼
Extension opens the Brightspace source (PDF page or highlighted text)
```

Storage is local ChromaDB plus JSON files under `api/data/`. Each course has its own collection. There is no conversation history: each `/chat` request is `course_id` + `message`.

## Key engineering

- **Course-isolated collections** — ingest and retrieve against `course_{uuid}` only
- **Ingest pipeline** — PDF/HTML parse, navigation-page filter, token chunks, document-type labels, embeddings
- **Query planning** — LLM structured output: intent, question type, English retrieval queries
- **Intent-aware routing** — syllabus / lecture / assignment tiers, with early-stop for course-info questions
- **Multi-query retrieval** — parallel searches, merge by chunk, coverage-aware Top-K
- **Resource resolution** — map `hw1` / `lab2` to a synced topic and optionally scope retrieval
- **Assignment shortcut** — due date and submit-location answers come from the Brightspace assignment object, not the LLM
- **Grade-policy filter** — course-wide grade weights are not answered from a project rubric
- **Grounded generation** — context has no URLs; the model cites `[SOURCE N]`; the API attaches links
- **Chrome extension** — Brightspace discovery, sync progress, citation open/highlight

## If you only have five minutes, start here

| File | Why |
| --- | --- |
| [`api/app/services/retrieval_router.py`](api/app/services/retrieval_router.py) | The retrieval design: intent tiers, early-stop, multi-query merge, identifier boost, scoped resource slots |
| [`api/app/services/rag.py`](api/app/services/rag.py) (`chat_with_rag`) | End-to-end answer path: planner, assignment shortcut, policy filter, prompt, citation parse |
| [`api/app/services/query_intent.py`](api/app/services/query_intent.py) | Structured query plan plus a deterministic override for course-wide grading questions |
| [`extension/src/content/brightspace-indexer.ts`](extension/src/content/brightspace-indexer.ts) | Real LMS ingest: module tree + TOC coverage, fetch fallbacks, assignment pipeline |
| [`api/tests/test_retrieval_router.py`](api/tests/test_retrieval_router.py) and [`api/tests/test_grade_policy.py`](api/tests/test_grade_policy.py) | How routing and grade-scope bugs were locked down |

## Example query flow

All names below are fictional (`sample_data/intro-numerical-methods`).

**“Where is Newton's method explained?”**

1. `plan_query` labels the question `LEARNING` and emits search queries such as `Newton's method explanation`
2. `planned_retrieval` searches the NUM-201 collection, lecture-first
3. Matching lecture chunks become `[SOURCE N]` context (no URLs in the prompt)
4. The model answers from those chunks; the API returns source links
5. The extension can open the lecture page and jump to the cited page

**“When is Homework 1 due?”**

1. Identifier matching resolves `Homework 1` to a synced assignment object
2. The aspect is `due`, so the API returns the structured due date
3. No chat completion is required for that answer

## Tech stack

| Layer | Used here |
| --- | --- |
| Extension | Chrome Manifest V3, React, TypeScript, Vite, esbuild |
| API | FastAPI, Pydantic, Uvicorn |
| Retrieval / generation | OpenAI embeddings + chat, custom router (not LangChain) |
| Storage | ChromaDB (local persistent client), JSON course registry and assignment objects |
| Tests | Python `unittest`, Vitest |

## Running locally

The backend and the sample-data path run without Brightspace. Full course sync needs an authenticated Brightspace session in Chrome.

### 1. API

```bash
cd api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OPENAI_API_KEY
uvicorn app.main:app --reload --port 8001
```

OpenAPI: http://localhost:8001/docs

### 2. Ingest the sample course

```bash
curl -s http://localhost:8001/api/v1/ingest/batch \
  -H "Content-Type: application/json" \
  -d @../sample_data/intro-numerical-methods/ingest_batch.json
```

Note the returned `course_id`, then:

```bash
curl -s http://localhost:8001/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"course_id":"<course_id>","message":"Where is Newton'\''s method explained?"}'
```

Without `OPENAI_API_KEY`, ingest cannot embed. Chat can still return a retrieval excerpt or an assignment-object answer.

### 3. Extension (optional)

```bash
cd extension
npm install
npm run build
```

Chrome → `chrome://extensions` → Load unpacked → `extension/dist/`

Then open a Brightspace course page, sync, and ask from the side panel.

### Tests

```bash
cd api && python -m unittest discover -s tests -v
cd extension && npm test
```

## Layout

```
api/           FastAPI app, retrieval, ingest, tests
extension/     Chrome MV3 side panel, indexer, highlighter
sample_data/   Fictional ingest payload
```
