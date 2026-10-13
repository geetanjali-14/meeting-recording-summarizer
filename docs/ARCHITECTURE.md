# Architecture — Meeting Recording Summarizer

> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-13  
> **Document Owner:** Architecture Team  

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Component Responsibilities & Runtime Separation](#2-component-responsibilities--runtime-separation)
3. [Repository Structure](#3-repository-structure)
4. [Data Flow — Direct Upload to Intelligence (11-Step Pipeline)](#4-data-flow--direct-upload-to-intelligence-11-step-pipeline)
5. [Asynchronous Processing Engine: Celery + Redis](#5-asynchronous-processing-engine-celery--redis)
6. [Provider Abstraction Architecture](#6-provider-abstraction-architecture)
   - 6.1 [TranscriptionProvider (Whisper Turbo Baseline)](#61-transcriptionprovider-whisper-turbo-baseline)
   - 6.2 [DiarizationProvider (pyannote Community-1 Baseline)](#62-diarizationprovider-pyannote-community-1-baseline)
   - 6.3 [LLMProvider (GPT-OSS Candidates & Targeted Verification)](#63-llmprovider-gpt-oss-candidates--targeted-verification)
   - 6.4 [StorageProvider (Cloudflare R2 / S3)](#64-storageprovider-cloudflare-r2--s3)
7. [Frontend Architecture (Next.js)](#7-frontend-architecture-nextjs)
8. [Authentication, Authorization & Tenant Isolation](#8-authentication-authorization--tenant-isolation)
9. [Database Architecture & Authoritative State](#9-database-architecture--authoritative-state)
10. [State Machines & Transition Integrity](#10-state-machines--transition-integrity)
11. [Configuration Architecture](#11-configuration-architecture)
12. [Security & Untrusted Data Isolation](#12-security--untrusted-data-isolation)
13. [Observability & Cost Tracking](#13-observability--cost-tracking)
14. [Performance Targets & Reliability Matrix](#14-performance-targets--reliability-matrix)
15. [Architectural Decision Summary](#15-architectural-decision-summary)

---

## 1. System Architecture Overview

The **Meeting Recording Summarizer** is architected from day one as a production-grade, asynchronous system. The local development environment serves purely for testing and verification; all architectural patterns, persistence layers, and service contracts assume a cloud deployment environment.

### Core Architectural Principles
1. **Decoupled API and Worker Runtimes:** HTTP API request handling and asynchronous background processing are separated into distinct runtime roles.
2. **Direct-to-Storage Ingestion:** Large media binaries (up to 500 MB) are uploaded directly from the browser to private object storage via pre-signed `PUT` authorizations, never streaming through or buffering on the API server.
3. **Celery + Redis Task Execution with PostgreSQL Authoritative State:** Task execution is managed by Celery worker processes using Redis as the high-throughput task broker. PostgreSQL is the authoritative source of truth for durable meeting metadata, processing status, attempt counts, errors, and analytical results (Redis transports tasks; it is not the sole state store).
4. **Relational Transcript Segments & Speaker Diarization:** Speech-to-text outputs are persisted as discrete `TranscriptSegment` relational rows. Speaker turns are detected via diarization (pyannote Community-1 baseline), aligned to transcript segments, and stored as anonymous speaker labels (`SPEAKER_00`). Real participant names are mapped separately.
5. **Deterministic Evidence Traceability:** All extracted insights (decisions, action items, risks, open questions) link to `source_segment_ids`. Timestamps are derived deterministically by backend logic from segment metadata.
6. **Bounded Context & Targeted Verification:** Intelligence extraction is orchestrated by a single bounded `MeetingAnalysisAgent`. When the transcript fits the context window, a single structured LLM call is executed. If context limits are exceeded, bounded hierarchical chunking is used. A secondary targeted verification model call is invoked only when needed for ambiguous or high-impact claims.
7. **Strict Provider Decoupling:** LLM, Speech-to-Text, Diarization, and Object Storage are encapsulated behind abstract interfaces (`LLMProvider`, `TranscriptionProvider`, `DiarizationProvider`, `StorageProvider`).

### High-Level System Architecture

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER BROWSER                               │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                 Next.js + TypeScript + Tailwind CSS             │   │
│   │                                                                 │   │
│   │  Pages: Dashboard · Upload Dropzone · Live Status · Intelligence│   │
│   │  Speaker Mapping · Transcript Playback                          │   │
│   │  API Client: Typed REST Client (/api/v1/)                       │   │
│   └────────────────────┬──────────────────────┬─────────────────────┘   │
└────────────────────────┼──────────────────────┼─────────────────────────┘
                         │ HTTPS REST           │ Direct PUT (Pre-signed URL)
                         ▼                      ▼
┌────────────────────────────────┐     ┌──────────────────────────────────┐
│      FastAPI HTTP API          │     │    Private Object Storage        │
│  (Runtime Role: Web Server)    │     │    (Cloudflare R2 / S3)          │
│                                │     │                                  │
│  - /api/v1/health              │     │  users/{user_id}/recordings/     │
│  - /api/v1/meetings (CRUD)     │     │                                  │
│  - /api/v1/meetings/{id}/      │     │  Private bucket access only;     │
│    confirm-upload              │     │  Zero egress fees on R2          │
│  - /api/v1/meetings/{id}/status│     └────────────────┬─────────────────┘
│  - /api/v1/meetings/{id}/      │                      │
│    transcript                  │                      │ StorageProvider
│  - /api/v1/meetings/{id}/      │                      │ (Presigned URLs /
│    analysis                    │                      │  Boto3 download)
│  - JWT Verification & Auth     │                      │
└───────────────┬────────────────┘                      │
                │                                       │
                │ 1. Verify & Write Meeting (Postgres)  │
                │ 2. Enqueue Task (Redis)               │
                ▼                                       │
┌────────────────────────────────┐                      │
│       Redis Task Broker        │                      │
│  (Celery Message Transport)    │                      │
└───────────────┬────────────────┘                      │
                │                                       │
                │ Celery Task Dispatch                  │
                │ (acks_late=True)                      │
                ▼                                       │
┌────────────────────────────────┐                      │
│    Dedicated Celery Worker     │                      │
│   (Runtime Role: Worker)       │◄─────────────────────┘
│                                │
│  - Audio Extraction (FFmpeg)   │     ┌──────────────────────────────────┐
│  - StorageProvider (Download)  │     │      External AI Providers       │
│  - TranscriptionProvider       │────►│                                  │
│  - DiarizationProvider         │     │  TranscriptionProvider:          │
│  - Turn Alignment Engine       │     │  - Groq Whisper Large V3 Turbo   │
│  - MeetingAnalysisAgent        │     │  - Whisper Large V3 / Hosted STT │
│  - Targeted Verification       │     │                                  │
│  - Evidence Linkage Validator  │────►│  DiarizationProvider:            │
│  - State & Result Commits      │     │  - pyannote Community-1          │
└───────────────┬────────────────┘     │                                  │
                │                      │  LLMProvider:                    │
                │ Durable Updates      │  - GPT-OSS 120B (Quality via Groq│
                ▼                      │  - GPT-OSS 20B (Cost via Groq)   │
┌────────────────────────────────┐     │  - Commercial fallback providers │
│       PostgreSQL Database      │     └──────────────────────────────────┘
│       (Supabase / Managed)     │
│                                │
│  - Authoritative Job State     │
│  - Users, Meetings, Recordings │
│  - Transcripts & Segments      │
│  - Analyses, Topics, Decisions │
└────────────────────────────────┘
```

---

## 2. Component Responsibilities & Runtime Separation

### 2.1 Next.js Frontend
- **Responsibilities:** Renders responsive UI, initiates upload authorizations, uploads media directly to Cloudflare R2 via pre-signed URL, polls `/status`, renders structured analysis, allows click-through from evidence badges to transcript segments, provides speaker label mapping (`SPEAKER_00` $\rightarrow$ "Alice").
- **Forbidden:** No business logic, no direct third-party AI provider calls, no raw credential storage.

### 2.2 FastAPI Backend (API Runtime Role)
- **Responsibilities:** Validates JWT tokens, verifies tenant resource ownership (`WHERE user_id = :user_id`), generates pre-signed PUT URLs via `StorageProvider`, verifies object existence via `HeadObject`, creates `Meeting` and `ProcessingJob` records, dispatches Celery tasks to Redis, exposes `/api/v1/` REST endpoints.
- **Forbidden:** Does not process long-running transcription, diarization, or LLM calls in HTTP handlers; does not buffer large media files in memory or disk.

### 2.3 Dedicated Celery Worker (Worker Runtime Role)
- **Responsibilities:** Consumes tasks from Redis broker, normalizes audio using FFmpeg, calls `TranscriptionProvider` and `DiarizationProvider`, aligns transcript segments with speaker turns, executes `MeetingAnalysisAgent`, runs targeted verification when needed, commits results to PostgreSQL, acknowledges tasks with `acks_late=True`.
- **Forbidden:** Does not serve HTTP traffic; does not accept external HTTP requests.

### 2.4 PostgreSQL Database
- **Responsibilities:** Authoritative persistence for all domain entities, durable record of job status, attempts, error codes, referential integrity cascades, array storage for evidence IDs.
- **Forbidden:** Does not store binary media blobs; does not depend on proprietary vendor extensions for core domain operations.

### 2.5 Redis Task Broker
- **Responsibilities:** Fast, low-latency in-memory transport for Celery task queuing and scheduling.
- **Forbidden:** Not the sole source of truth for job completion or application data.

### 2.6 StorageProvider (Cloudflare R2 / S3)
- **Responsibilities:** Secure, private persistence for media binaries. Generates time-bounded pre-signed `PUT` URLs (15-min TTL) for uploads and temporary `GET` URLs for worker downloads.
- **Forbidden:** No public read permissions; no unauthenticated access.

---

## 3. Repository Structure

```text
meeting-summarizer/
│
├── backend/
│   ├── app/
│   │   ├── api/                         # HTTP routing & controller layer
│   │   │   └── v1/
│   │   │       ├── router.py            # Mounts all v1 sub-routers (/api/v1/)
│   │   │       ├── deps.py              # Auth & DB dependency injectors
│   │   │       ├── health.py            # /api/v1/health probe
│   │   │       ├── meetings.py          # Meeting lifecycle CRUD & signed upload URLs
│   │   │       ├── uploads.py           # Upload confirmation (/confirm-upload)
│   │   │       ├── status.py            # Job status polling
│   │   │       ├── transcript.py        # Segmented transcript retrieval
│   │   │       └── analysis.py          # Structured intelligence retrieval
│   │   │
│   │   ├── core/                        # Centralized configuration & cross-cutting concerns
│   │   │   ├── config.py               # Pydantic BaseSettings (Single Source of Truth)
│   │   │   ├── celery_app.py           # Celery configuration & Redis broker setup
│   │   │   ├── logging.py              # Structured JSON logging & context vars
│   │   │   └── security.py             # Asymmetric/JWKS JWT validation & user context
│   │   │
│   │   ├── tasks/                       # Celery task definitions
│   │   │   ├── meeting_tasks.py         # Main meeting processing workflow task
│   │   │   └── reconciliation_tasks.py  # Stale job recovery & cleanup tasks
│   │   │
│   │   ├── models/                      # SQLAlchemy 2.0 Declarative Models
│   │   │   ├── base.py                 # TimestampMixin, UUIDMixin
│   │   │   ├── user.py
│   │   │   ├── meeting.py
│   │   │   ├── recording.py
│   │   │   ├── processing_job.py        # Tracks status, stage, celery_task_id, attempts
│   │   │   ├── transcript.py           # Transcript & TranscriptSegment models
│   │   │   ├── meeting_analysis.py     # MeetingAnalysis, Topic, Decision, ActionItem, etc.
│   │   │   └── chat.py                 # ChatSession, ChatMessage (Future Phase 12)
│   │   │
│   │   ├── repositories/                # Data access layer with mandatory user_id scoping
│   │   │   ├── meeting_repository.py
│   │   │   ├── job_repository.py
│   │   │   ├── transcript_repository.py
│   │   │   └── analysis_repository.py
│   │   │
│   │   ├── services/                    # Deterministic business logic & orchestration
│   │   │   ├── meeting_service.py
│   │   │   ├── upload_service.py
│   │   │   ├── processing_service.py
│   │   │   ├── audio_service.py         # FFmpeg inspection, extraction, normalization
│   │   │   ├── transcription_service.py
│   │   │   ├── diarization_service.py   # Speaker turn detection & segment alignment
│   │   │   └── analysis_service.py
│   │   │
│   │   ├── agents/                      # Bounded AI extraction agents
│   │   │   ├── meeting_analysis_agent.py
│   │   │   └── verification_agent.py    # Targeted verification for ambiguous claims
│   │   │
│   │   ├── prompts/                     # Strictly delimited system & extraction prompts
│   │   │   └── meeting_analysis_prompt.py
│   │   │
│   │   ├── providers/                   # Abstract base classes & concrete adapters
│   │   │   ├── storage/
│   │   │   │   ├── base.py              # StorageProvider ABC
│   │   │   │   └── r2_provider.py       # Cloudflare R2 / S3 Boto3 adapter
│   │   │   ├── transcription/
│   │   │   │   ├── base.py              # TranscriptionProvider ABC
│   │   │   │   ├── groq_whisper.py      # Groq Whisper Large V3 Turbo adapter
│   │   │   │   └── hosted_whisper.py    # Whisper Large V3 / alternative adapter
│   │   │   ├── diarization/
│   │   │   │   ├── base.py              # DiarizationProvider ABC
│   │   │   │   └── pyannote_provider.py # pyannote Community-1 adapter
│   │   │   └── llm/
│   │   │       ├── base.py              # LLMProvider ABC
│   │   │       └── groq_provider.py     # GPT-OSS 120B / 20B via Groq
│   │   │
│   │   └── schemas/                     # Pydantic v2 Request/Response/Domain models
│   │       ├── meeting.py
│   │       ├── upload.py
│   │       ├── job.py
│   │       ├── transcript.py
│   │       └── analysis.py
│   │
│   ├── migrations/                      # Alembic migrations
│   │   ├── env.py
│   │   └── versions/
│   │
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── security/
│       └── evaluation/
│           └── datasets/                # AI evaluation benchmark meeting sets
│
├── frontend/                            # Next.js Application
│   ├── src/
│   │   ├── app/                         # Next.js App Router pages
│   │   ├── components/                  # UI components (UploadDropzone, EvidenceBadge, etc.)
│   │   ├── lib/                         # API client & auth hooks
│   │   └── types/                       # TypeScript interfaces
│   ├── package.json
│   ├── tsconfig.json
│   └── tailwind.config.js
│
├── docs/                                # Authoritative Architecture & Planning Suite
├── .env.example
└── README.md
```

---

## 4. Data Flow — Direct Upload to Intelligence (11-Step Pipeline)

The baseline processing pipeline consists of 11 sequential stages:

```text
Browser                 FastAPI API             Cloudflare R2          Redis / Celery          PostgreSQL
   │                         │                        │                      │                     │
   │── 1. POST /meetings ───►│                        │                      │                     │
   │   { title, format }     │                        │                      │                     │
   │                         │── Create Meeting Row ──────────────────────────────────────────────►│
   │                         │   & Gen Presigned PUT ─►│                     │                     │
   │                         │   (15 min TTL)         │                      │                     │
   │◄── 2. Signed Upload URL─│                        │                      │                     │
   │                         │                        │                      │                     │
   │── 3. Direct Binary PUT ─────────────────────────►│                      │                     │
   │   (with progress bar)   │                        │                      │                     │
   │◄── 4. HTTP 200 OK ───────────────────────────────│                      │                     │
   │                         │                        │                      │                     │
   │── 5. POST /confirm ────►│                        │                      │                     │
   │                         │── HeadObject Check ───►│                      │                     │
   │                         │── Enqueue Celery Task ───────────────────────►│                     │
   │                         │── Update Status=QUEUED ────────────────────────────────────────────►│
   │◄── 6. Confirmed (202) ──│                        │                      │                     │
   │                         │                        │                      │                     │
   │ [Polls /status]         │                        │                      ▼                     │
   │                         │                        │              Celery Worker Task            │
   │                         │                        │              (acks_late=True)              │
   │                         │                        │                      │                     │
   │                         │                        │                      │── Stage 1: Validate recording & metadata
   │                         │                        │                      │── Stage 2: Extract & normalize with FFmpeg
   │                         │                        │                      │── Stage 3: Transcribe audio (Whisper Turbo)
   │                         │                        │                      │── Stage 4: Run speaker diarization (pyannote)
   │                         │                        │                      │── Stage 5: Align segments with speaker turns
   │                         │                        │                      │── Stage 6: Persist TranscriptSegments ───► PostgreSQL
   │                         │                        │                      │── Stage 7: Prepare bounded analysis input
   │                         │                        │                      │── Stage 8: Generate insights (GPT-OSS via Groq)
   │                         │                        │                      │── Stage 9: Validate schema & evidence references
   │                         │                        │                      │── Stage 10: Targeted verification (if needed)
   │                         │                        │                      │── Stage 11: Persist analysis & mark COMPLETED ──► PostgreSQL
   │                         │                        │                      │                     │
   │── 7. Poll Status ──────►│                                                                     │
   │◄── Status: COMPLETED ───│                                                                     │
   │── 8. GET /analysis ────►│                                                                     │
   │◄── Intelligence View ───│                                                                     │
```

---

## 5. Asynchronous Processing Engine: Celery + Redis

### 5.1 Architecture & Separation of Concerns
- **Task Broker (Redis):** Handles message transport, rate limiting, and queueing.
- **Authoritative Data Store (PostgreSQL):** Stores durable entity records, job stage (`stage`), status (`status`), attempt counts (`attempt`), and error codes (`error_code`).
- **Worker Runtime (Celery):** Executes background compute independently from FastAPI.

### 5.2 Celery Reliability & Execution Invariants
1. **Late Acknowledgment (`acks_late = True`):** Tasks are acknowledged only **after** successful completion. If a worker process terminates or crashes mid-task, Celery does not lose the task.
2. **Reject on Worker Lost (`reject_on_worker_lost = True`):** If a worker pod crashes abruptly, the broker rejects the unacknowledged message and requeues it for another worker.
3. **Prefetch Limits (`worker_prefetch_multiplier = 1`):** Workers prefetch only one long-running task at a time, preventing task hoarding.
4. **Idempotency & Checkpointing:** Tasks verify PostgreSQL status before execution. If transcription and diarization segments already exist for a meeting, a retried task reuses the existing segments rather than repeating expensive speech-to-text calls.
5. **Durable Reconciliation:** A scheduled reconciliation task scans PostgreSQL for jobs in non-terminal states whose Celery tasks are no longer active in Redis, safely resetting them or marking them `FAILED` after max attempts.

---

## 6. Provider Abstraction Architecture

### 6.1 TranscriptionProvider (Whisper Turbo Baseline)
```text
TranscriptionService ──► TranscriptionProvider (ABC)
                             ├── GroqWhisperProvider (Whisper Large V3 Turbo baseline)
                             ├── HostedWhisperProvider (Whisper Large V3 candidate)
                             └── CloudAlternativeProvider (Deepgram Nova-2 / Hosted API)
```
- Audio and video inputs supported via FFmpeg preprocessing.
- Large recordings (> 25MB or > 1 hour) are chunked where provider limits dictate.
- Caching: If recording audio and configuration have not changed, transcription results are reused.

### 6.2 DiarizationProvider (pyannote Community-1 Baseline)
```text
DiarizationService ──► DiarizationProvider (ABC)
                           ├── PyannoteProvider (pyannote Community-1 baseline)
                           └── HostedDiarizationProvider (Cloud alternative)
```
- Detects speaker turns and assigns anonymous labels (`SPEAKER_00`, `SPEAKER_01`).
- **Timestamp Alignment:** Reconciles word/segment-level transcription timestamps with speaker-turn intervals using maximum time-overlap heuristics.
- Speaker labels are stored separately from user-assigned participant names.

### 6.3 LLMProvider (GPT-OSS Candidates & Targeted Verification)
```text
LLMService ──► LLMProvider (ABC)
                   ├── GroqProvider (GPT-OSS 120B quality candidate / GPT-OSS 20B low-cost)
                   ├── OpenAIProvider (Fallback option)
                   └── LocalProvider (Future on-premise)
```
- **Context Handling:** Standard transcripts receive a single structured call. Large transcripts trigger bounded hierarchical chunking (chunks $\rightarrow$ compact intermediate facts $\rightarrow$ synthesis).
- **Targeted Verification Model Call:** Invoked only when needed to verify ambiguous, unsupported, or high-impact claims, avoiding expensive blanket critic LLM passes on every run.

### 6.4 StorageProvider (Cloudflare R2 / S3)
```text
StorageService ──► StorageProvider (ABC)
                       ├── R2StorageProvider (Cloudflare R2, zero egress fees)
                       └── S3StorageProvider (AWS S3 compatible)
```

---

## 7. Frontend Architecture (Next.js)

- **Framework:** Next.js + TypeScript + Tailwind CSS.
- **Data Fetching:** Typed REST client for `/api/v1/` endpoints with TanStack React Query for status polling and client caching.
- **Direct Upload Dropzone:** Initiates upload authorization, executes direct `PUT` to R2 using XMLHttpRequest with progress percentage, and confirms completion.
- **Meeting Intelligence View:** Collapsible sections for executive summary, topics, decisions, action items, risks, and questions.
- **Evidence Click-Through:** Evidence badges link directly to the corresponding `TranscriptSegment` in the transcript viewer.
- **Speaker Mapping:** Interface allowing users to assign participant names to detected speaker labels (`SPEAKER_00` $\rightarrow$ "Alice").

---

## 8. Authentication, Authorization & Tenant Isolation

1. **JWT Verification:** Authenticated requests pass `Authorization: Bearer <JWT>`. The backend validates token signatures against Supabase / OIDC JWKS public keys, verifying issuer, audience, expiration, and subject (`sub`).
2. **Tenant Isolation:** Multi-tenancy is strictly isolated at the database layer. Every repository query explicitly adds `WHERE user_id = :authenticated_user_id`.
3. **IDOR Defense:** Querying another user's meeting ID returns **HTTP 404 NOT FOUND** to prevent ID enumeration.

---

## 9. Database Architecture & Authoritative State

PostgreSQL stores all authoritative entity records:

```text
User (UUID)
 └── Meeting (UUID, user_id, title, status, meeting_date, speaker_mappings)
       ├── Recording (UUID, user_id, storage_key, file_size, duration, status)
       ├── ProcessingJob (UUID, user_id, status, stage, celery_task_id, attempt)
       ├── Transcript (UUID, user_id, language, duration)
       │    └── TranscriptSegment (UUID, sequence, start, end, speaker_label, text)
       ├── MeetingAnalysis (UUID, user_id, title, summary, model_name, cost_usd)
       │    ├── Topic (UUID, sequence, title, description, start_time)
       │    ├── Decision (UUID, decision, source_segment_ids: UUID[])
       │    ├── ActionItem (UUID, description, owner, due_date, source_segment_ids: UUID[])
       │    ├── Risk (UUID, description, severity, source_segment_ids: UUID[])
       │    └── OpenQuestion (UUID, question, source_segment_ids: UUID[])
       └── ChatSession (UUID, user_id) [Phase 12 Future]
            └── ChatMessage (UUID, role, content, citation_segment_ids)
```

---

## 10. State Machines & Transition Integrity

### 10.1 ProcessingJob State Machine
- **Allowed States:** `PENDING`, `TRANSCRIBING`, `DIARIZING`, `ANALYZING`, `COMPLETED`, `FAILED`, `CANCELLED`
- **Allowed Transitions:**
  - `PENDING` $\rightarrow$ `TRANSCRIBING`
  - `TRANSCRIBING` $\rightarrow$ `DIARIZING`
  - `DIARIZING` $\rightarrow$ `ANALYZING`
  - `ANALYZING` $\rightarrow$ `COMPLETED`
  - Any active state $\rightarrow$ `FAILED` (if attempt < max_attempts, resets to `PENDING` with retry backoff)
  - Any active state $\rightarrow$ `CANCELLED` (if meeting deleted)
- **Invalid Transitions:** `COMPLETED` $\rightarrow$ `PENDING`, `CANCELLED` $\rightarrow$ `ANALYZING`

---

## 11. Configuration Architecture

Configuration flows strictly through validated Pydantic Settings:

```text
Environment Variables (.env / PaaS config)
      ↓
Pydantic BaseSettings (app/core/config.py)
      ↓
FastAPI Dependencies & Celery Configuration
      ↓
Domain Services & Provider Adapters
```

**Invariant:** Business logic, tasks, and routes **never** call `os.environ` directly.

---

## 12. Security & Untrusted Data Isolation

- **Prompt Injection Defense:** Transcripts are treated as untrusted data wrapped in boundary delimiters (`<UNTRUSTED_TRANSCRIPT>`).
- **Private Storage:** Pre-signed upload URLs expire in $\le 15$ minutes. Public access is disabled on Cloudflare R2 buckets.
- **Log Hygiene:** Plaintext transcripts, credentials, JWTs, and signed URLs are strictly redacted from structured logs.

---

## 13. Observability & Cost Tracking

- **Structured JSON Logging:** Every log event includes `request_id`, `meeting_id`, `job_id`, `celery_task_id`, `provider`, `step`, and `duration_ms`.
- **Cost Metrics:** Every completed analysis records:
  - `prompt_tokens`
  - `completion_tokens`
  - `total_tokens`
  - `cost_estimate_usd`
  - `pricing_version` (protects historical records from vendor pricing changes)

---

## 14. Performance Targets & Reliability Matrix

### 14.1 Target Classifications
- **P0 (Mandatory Correctness):** Tenant isolation, zero hallucination, Celery task crash recovery, transactional consistency.
- **P1 (Empirical Performance Targets):**
  - Direct upload URL generation: < 500ms
  - 30-minute recording end-to-end processing: Target < 5 minutes
  - Non-upload API p95 response time: Target < 500ms
  - Status polling response time: Target < 100ms
- **P2 (Future Optimizations):** Streaming responses for Q&A, WebRTC ingest.

### 14.2 Reliability Matrix

| Scenario | System Mitigation |
|---|---|
| Direct upload network interruption | Browser shows retry; meeting stays in `PRESIGNED` state until confirmed |
| Celery worker crashes mid-task | `acks_late=True` and `reject_on_worker_lost=True` ensure task is requeued; PostgreSQL state guides safe resumption |
| STT / LLM provider rate limit (429) | Celery task catches error, schedules retry with exponential backoff, or routes to fallback provider |
| LLM context overflow | Automatic fallback to bounded hierarchical chunking & synthesis |
| Malformed LLM JSON output | Strict Pydantic validation failure triggers automated retry with repair prompt |
| Meeting deletion requested | Deletion state machine marks `DELETING`, removes R2 object, purges DB rows |

---

## 15. Architectural Decision Summary

| Domain | Mandatory Decision | Replaceable Implementation |
|---|---|---|
| **Database** | PostgreSQL from Day One (Authoritative Store) | Supabase / RDS / Self-Hosted |
| **Task Queue** | Celery + Redis Broker | Redis Cloud / Valkey / Celery Worker |
| **Storage** | S3-Compatible Private Storage | Cloudflare R2 / AWS S3 |
| **Media Processing**| FFmpeg normalization & extraction | Worker container subprocess |
| **Transcription** | TranscriptionProvider Interface | Groq Whisper Large V3 Turbo (baseline) / Whisper V3 |
| **Diarization** | DiarizationProvider Interface | pyannote Community-1 (baseline) |
| **LLM Analysis** | LLMProvider Interface | GPT-OSS 120B / GPT-OSS 20B via Groq |
| **Auth** | Standard JWT Verification | Supabase Auth / OIDC |
| **Frontend** | Next.js + TypeScript + Tailwind CSS | Vercel / Docker Container |
