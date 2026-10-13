# PROJECT_PLAN.md — Meeting Recording Summarizer

> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-13  
> **Document Owner:** Architecture Team  

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [Goals](#2-goals)
3. [Technology Stack Baseline](#3-technology-stack-baseline)
4. [MVP Scope & Feature List](#4-mvp-scope--feature-list)
5. [Background Processing Workflow](#5-background-processing-workflow)
6. [Phased Implementation Roadmap](#6-phased-implementation-roadmap)
7. [Success Criteria](#7-success-criteria)
8. [Key Technical Risks & Mitigations](#8-key-technical-risks--mitigations)
9. [Deferred Architecture & Out of Scope](#9-deferred-architecture--out-of-scope)

---

## 1. Product Vision

The **Meeting Recording Summarizer** is a production-first web application that accepts audio or video recordings of meetings and returns structured, human-readable intelligence: an authoritative segmented transcript with speaker attribution, a concise executive summary, a list of action items with owners and deadlines, key decisions made, topics discussed, blockers/risks, and open questions.

The system is designed for professionals and teams who generate recordings from any source (Zoom, Google Meet, Teams, in-person captures, voice memos) and need consistent, reliable output on every file. The primary design constraint is **correctness, evidence traceability, and reliability over speed**: a summary that is wrong or hallucinates commitments is worse than no summary at all. The secondary constraint is cost efficiency — the pipeline uses low-cost, high-throughput provider abstractions without sacrificing structured precision.

---

## 2. Goals

### Primary Goals

| # | Goal | Definition of Done |
|---|------|--------------------|
| G1 | Accept common audio/video formats | MP3, MP4, M4A, WAV, WEBM, OGG uploads succeed via direct pre-signed upload to private storage |
| G2 | Produce timestamped transcripts with speaker diarization | Segmented transcript with sequence numbers, timestamps, and speaker labels aligned with turns |
| G3 | Extract structured meeting intelligence | Executive summary, action items, decisions, topics, risks, and open questions returned with evidence links |
| G4 | Persist results with configurable retention | Each user sees only their own recordings; results are managed through a configurable retention and deletion lifecycle |
| G5 | Expose a stable versioned API | All features available via versioned REST API (`/api/v1/`) |
| G6 | Run reliably in production | Celery workers + Redis task broker coordinate asynchronous execution; PostgreSQL stores authoritative state |

### Secondary Goals

| # | Goal | Rationale |
|---|------|-----------|
| S1 | Strict provider abstractions | Decouple LLM, STT, diarization, and storage behind abstract interfaces |
| S2 | Cost & token observability | Track per-job token usage, provider metrics, and estimated cost with pricing version metadata |
| S3 | Meaningful error reporting & recovery | Failed jobs record structured error codes and recover safely without duplicating expensive completed work |
| S4 | Async job status visibility | Users observe progress of transcription/diarization/analysis jobs via polling |
| S5 | Extensibility toward Q&A | Data model cleanly accommodates future conversational Q&A without schema rewrites |

---

## 3. Technology Stack Baseline

| Layer | Recommended Technology | Purpose |
|---|---|---|
| **Frontend** | Next.js + TypeScript + Tailwind CSS | Web application and meeting dashboard |
| **Backend API** | Python + FastAPI | APIs, authentication, business rules, and workflow coordination |
| **Validation** | Pydantic | Request validation and structured AI output validation |
| **ORM & Migrations** | SQLAlchemy + Alembic | Database access and schema migrations |
| **Database** | PostgreSQL (initially Supabase) | Durable application data and authoritative job state |
| **Background Jobs** | Celery + Redis | Asynchronous processing, retries, and worker execution |
| **Object Storage** | Cloudflare R2 (S3-compatible abstraction) | Private audio and video recording storage |
| **Audio Processing** | FFmpeg | Media inspection, audio stream extraction, and normalization |
| **Transcription** | Groq-hosted Whisper Large V3 Turbo (initial candidate) | Timestamped speech transcription (evaluated vs Whisper Large V3 & alternative) |
| **Speaker Diarization** | pyannote Community-1 (initial baseline) | Detect speaker turns and assign speaker labels |
| **Meeting Analysis** | GPT-OSS 120B (quality) / GPT-OSS 20B (cost) via Groq | Structured meeting intelligence extraction |
| **Deployment** | Docker-compatible API and worker containers | Reproducible production deployment |
| **Testing** | Pytest, integration/security tests, AI evaluation dataset | Validate correctness, reliability, and model quality |
| **CI** | GitHub Actions | Automated quality, linting, and test checks |

---

## 4. MVP Scope & Feature List

### Authentication & Tenant Isolation
- [x] User registration & login via Supabase Auth (or standard OIDC)
- [x] Backend JWT validation (signature, issuer, audience, expiration, subject)
- [x] Strict tenant isolation: users can only access their own meetings (`WHERE user_id = :user_id`)
- [x] All API endpoints mounted under `/api/v1/`

### Private Object Storage & Direct Upload
- [x] Direct frontend-to-storage upload via pre-signed `PUT` URLs (Cloudflare R2)
- [x] Accepted formats: MP3, MP4, M4A, WAV, WEBM, OGG (up to 500 MB)
- [x] Media files never streamed through or buffered on the FastAPI server
- [x] Upload confirmation endpoint verifies stored object and enqueues processing job

### Decoupled Celery Worker Engine
- [x] Celery worker runtime using Redis as task broker
- [x] PostgreSQL stores authoritative job state, attempts, and results (Redis transports tasks)
- [x] Celery task late acknowledgment (`acks_late=True`, `reject_on_worker_lost=True`)
- [x] Idempotency controls and crash recovery without repeating completed work
- [x] Job states: `PENDING → TRANSCRIBING → DIARIZING → ANALYZING → COMPLETED | FAILED`

### Media Processing & Transcription
- [x] Media stream inspection and audio extraction/normalization via FFmpeg
- [x] `TranscriptionProvider` abstraction (Groq Whisper Large V3 Turbo baseline)
- [x] Speaker diarization via `DiarizationProvider` (pyannote Community-1 baseline)
- [x] Timestamp alignment between word/segment-level transcript and speaker-turn intervals
- [x] Persistent relational `TranscriptSegment` records (`id`, `sequence`, `start`, `end`, `speaker_label`, `text`)

### Meeting Intelligence (MeetingAnalysisAgent)
- [x] `LLMProvider` abstraction (GPT-OSS 120B quality candidate / GPT-OSS 20B low-cost candidate via Groq)
- [x] Single structured LLM call when transcript fits model context window
- [x] Bounded hierarchical processing (chunks → compact facts → synthesis) when transcript overflows context
- [x] Extracted fields: title, executive summary, topics, decisions, action items, risks, and open questions
- [x] First-class evidence linking: all decisions, action items, and risks reference `source_segment_ids`
- [x] Zero hallucination / null preference: unmentioned owners/dates evaluate strictly to `null`
- [x] Targeted verification model call invoked only when needed for ambiguous or high-impact claims

### Results & Management API
- [x] `POST /api/v1/meetings` — create meeting & request signed upload URL
- [x] `POST /api/v1/meetings/{id}/confirm-upload` — confirm upload & enqueue Celery job
- [x] `GET /api/v1/meetings` — list user's meetings with pagination and status
- [x] `GET /api/v1/meetings/{id}` — full meeting details
- [x] `GET /api/v1/meetings/{id}/status` — job status polling endpoint
- [x] `GET /api/v1/meetings/{id}/transcript` — ordered transcript segments with speaker attribution
- [x] `GET /api/v1/meetings/{id}/analysis` — structured intelligence with evidence links
- [x] `DELETE /api/v1/meetings/{id}` — cascading deletion across storage and database

### Next.js Frontend Dashboard
- [x] Next.js + TypeScript + Tailwind CSS web application
- [x] Direct upload dropzone with progress indicator
- [x] Meeting list and status polling view
- [x] Intelligence results dashboard with evidence click-through to transcript segments
- [x] Speaker label mapping interface (mapping `SPEAKER_00` to real participant names)

---

## 5. Background Processing Workflow

The background execution follows an authoritative 11-step pipeline:

```text
1. Validate the recording and its metadata.
2. Extract or normalize audio with FFmpeg where required.
3. Transcribe audio with the selected transcription provider (Whisper Turbo).
4. Run speaker diarization (pyannote Community-1).
5. Align transcript segments with diarization output intervals.
6. Persist timestamped transcript segments to PostgreSQL.
7. Prepare bounded input for meeting analysis.
8. Generate structured meeting insights (GPT-OSS via Groq).
9. Validate the schema (Pydantic) and evidence references (deterministic backend).
10. Perform targeted verification when needed (for ambiguous/high-impact claims).
11. Persist validated results and mark the job complete in PostgreSQL.
```

---

## 6. Phased Implementation Roadmap

```text
PHASE 0: Requirements + Architecture Correction + Freeze (CURRENT)
PHASE 1: Repository + Configuration + CI
PHASE 2: Database + Storage + Domain Contracts
PHASE 3: Authentication + Authorization
PHASE 4: Upload + Ingestion
PHASE 5: Worker + Job Engine (Celery + Redis)
PHASE 6: Transcription + Diarization (Groq Whisper Turbo & pyannote)
PHASE 7: Meeting Intelligence + Evidence Verification (GPT-OSS & Targeted Verification)
PHASE 8: Frontend (Next.js)
PHASE 9: End-to-End Reliability + Security
PHASE 10: AI Evaluation + Model Selection
PHASE 11: Deployment (Docker API & Worker)
PHASE 12: Meeting Q&A (Conversational Search)
```

---

## 7. Success Criteria

### Functional Correctness
- **SC-01 Direct Upload:** User receives pre-signed URL, uploads 100MB file directly to private R2 storage, confirms upload, and initiates Celery job.
- **SC-02 Media Normalization:** FFmpeg inspects media, extracts audio from video containers, and normalizes channels/sample rate cleanly.
- **SC-03 Diarization Alignment:** Spoken utterances are assigned distinct `speaker_label` values based on pyannote intervals.
- **SC-04 Evidence Integrity:** Every extracted decision and action item references valid `TranscriptSegment.id` values. Timestamps are derived deterministically by backend logic.
- **SC-05 Zero Hallucination:** Omitted owners/deadlines evaluate to `null` without fabricated entities.
- **SC-06 Tenant Isolation:** User A cannot access User B's meetings or recordings (returns HTTP 404).
- **SC-07 Deletion Lifecycle:** Deleting a meeting cascades across object storage, relational segments, analysis records, and job state.

### Reliability & Performance Targets
- **SC-08 Worker Crash Recovery:** Unacknowledged or aborted Celery tasks are recovered using `acks_late=True` and durable PostgreSQL state reconciliation.
- **SC-09 Transient Retry:** Network timeouts to external providers retry with exponential backoff up to 2 times before failing.
- **SC-10 Performance Target (P1):** End-to-end processing target for a 30-minute meeting is under 5 minutes on production cloud infrastructure.

---

## 8. Key Technical Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Context overflow on multi-hour meetings | Medium | High | Bounded hierarchical processing chunks transcript, extracts compact intermediate facts, and synthesizes final output. |
| R2 | Hallucinated action item owners/dates | Medium | High | Strict schema enforcement (`Optional[str]`), system prompt zero-hallucination rules, and deterministic citation validation. |
| R3 | Diarization & transcription timestamp drift | Medium | Medium | Align word/segment timestamps against pyannote speaker intervals using maximum overlap heuristics. |
| R4 | Celery worker crash mid-job | Medium | Medium | Late task acknowledgment (`acks_late=True`), task idempotency, and state checkpoints in PostgreSQL. |
| R5 | External provider rate limits or outages | Medium | Medium | Multi-provider abstraction with configurable fallbacks and exponential backoff on 429/503. |
| R6 | Orphaned storage objects on failed deletion | Low | Medium | Multi-step deletion pipeline with status `DELETING` and retry/logging on transient storage errors. |

---

## 9. Deferred Architecture & Out of Scope

The following items are explicitly deferred to prevent premature complexity:
- **LangGraph:** Defer until non-linear cyclic workflows with human-in-the-loop approvals are required. Python orchestration is sufficient for initial linear pipelines.
- **pgvector / Dedicated Vector DB:** Defer until Phase 12 Conversational Q&A retrieval is benchmarked against PostgreSQL full-text search.
- **Independent multi-agent swarms:** Defer; a single structured analysis agent with targeted verification avoids multi-agent latency, cost, and divergence.
- **Second Critic LLM on Every Run:** Defer; use deterministic Pydantic schema validation and evidence checks, reserving targeted verification model calls for ambiguous/high-impact claims.
- **Distributed Tracing Platform:** Defer until microservice extraction; structured JSON logging with `request_id` correlation is sufficient.
- **Persistent Job-Step History Table:** Defer; `ProcessingJob` state fields and structured logs track current step without table bloat.
- **Live streaming transcription:** Requires WebSocket streaming infrastructure; out of scope.
