# Controlled Implementation Roadmap

> **Document Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture Team  

---

## 1. Roadmap Overview & Governance

To maintain engineering discipline, prevent premature optimization, and ensure production readiness from the very first line of code, this implementation roadmap enforces a strictly phased approach.

### Implementation Discipline Principles
1. **Linear Progression:** Never start a phase until all prerequisite acceptance criteria of previous phases are fully verified.
2. **Explicit Non-Goals:** Every phase specifies forbidden tasks to prevent building speculative future features.
3. **Targeted Verification:** Each phase must conclude with executable automated tests demonstrating requirements compliance.
4. **No Premature Logic:** Do not write code for future phases in earlier phases.
5. **No Production SQLite / In-Process Worker Assumptions:** All phases build against the production-first architectural contracts (PostgreSQL, separate Worker runtime, private object storage, provider abstractions).

---

## 2. Phase-by-Phase Roadmap

```text
PHASE 0: Requirements + Architecture Correction + Freeze (COMPLETE)
   │
   ▼
PHASE 1: Repository + Configuration + CI
   │
   ▼
PHASE 2: Database + Storage + Domain Contracts
   │
   ▼
PHASE 3: Authentication + Authorization
   │
   ▼
PHASE 4: Upload + Ingestion
   │
   ▼
PHASE 5: Worker + Job Engine
   │
   ▼
PHASE 6: Transcription
   │
   ▼
PHASE 7: Meeting Intelligence
   │
   ▼
PHASE 8: Frontend
   │
   ▼
PHASE 9: End-to-End Reliability + Security
   │
   ▼
PHASE 10: AI Evaluation
   │
   ▼
PHASE 11: Deployment
   │
   ▼
PHASE 12: Meeting Q&A
```

---

### PHASE 0 — Requirements + Architecture Correction + Freeze (CURRENT — COMPLETED)
- **Objective:** Establish the comprehensive technical source of truth, architectural patterns, data models, API contracts, security bounds, and test strategies prior to writing application code.
- **Dependencies:** None.
- **Deliverables:**
  - Complete documentation suite in `docs/` (18 specification documents including `TRACEABILITY.md`, `GLOSSARY.md`, and `LEGAL_COMPLIANCE_NOTES.md`).
- **Acceptance Criteria:**
  - Architectural requirements, data models, and state machines frozen and internally consistent.
  - Zero application code created during planning phase.
- **Non-Goals:**
  - No code files, API routes, or database tables created.

---

### PHASE 1 — Repository + Configuration + CI
- **Objective:** Scaffold clean backend and frontend project structures with modern package management, validated centralized configuration, type checking, linting, and health probe.
- **Dependencies:** Phase 0.
- **Target Components:**
  - `backend/pyproject.toml` (FastAPI, Uvicorn, Celery, Redis, SQLAlchemy 2.0, Pydantic v2, Pydantic-Settings, Alembic, psycopg3, boto3, httpx, pytest).
  - `backend/app/main.py` (FastAPI initialization, CORS middleware, lifespan handler).
  - `backend/app/core/celery_app.py` (Celery initialization with Redis broker, `acks_late=True`, `reject_on_worker_lost=True`).
  - `backend/app/core/config.py` (Typed Pydantic `BaseSettings` validated configuration).
  - `backend/app/core/logging.py` (Structured JSON logging).
  - `backend/app/api/v1/health.py` (`GET /api/v1/health` probe).
  - `frontend/package.json`, `next.config.js`, `tsconfig.json` (Next.js 14, TypeScript, Tailwind CSS).
  - `.env.example`, `.gitignore`, `README.md`.
  - `.github/workflows/ci.yml` (Linting, type checks, test execution).
- **Acceptance Criteria:**
  - Backend boots via `uvicorn app.main:app` and returns HTTP 200 on `GET /api/v1/health`.
  - Frontend boots cleanly via `npm run dev` (Next.js).
  - Ruff, MyPy, and ESLint pass without warnings.
  - Configuration flows exclusively from environment variables to Pydantic Settings (no direct `os.environ` access in business logic).
- **Non-Goals:**
  - No database connection, no auth tokens, no storage buckets, no AI provider SDKs.

---

### PHASE 2 — Database + Storage + Domain Contracts
- **Objective:** Establish PostgreSQL schema, Alembic migration pipeline, repository data access layer with tenant isolation, and storage provider abstraction.
- **Dependencies:** Phase 1.
- **Target Components:**
  - `backend/app/models/` (SQLAlchemy declarative models for `User`, `Meeting` with `speaker_mappings`, `Recording`, `ProcessingJob` with `celery_task_id` & `stage`, `Transcript`, `TranscriptSegment` with `speaker_label`, `MeetingAnalysis`, `Topic`, `Decision`, `ActionItem`, `Risk`, `OpenQuestion`, `ChatSession`, `ChatMessage`).
  - `backend/app/repositories/` (Repository classes enforcing `WHERE user_id = :user_id`).
  - `backend/app/providers/storage/base.py` (`StorageProvider` abstract base class).
  - `backend/app/providers/storage/r2_provider.py` (Boto3-based Cloudflare R2 implementation).
  - `backend/migrations/` (Alembic environment and initial baseline migration).
  - `backend/tests/unit/test_repositories.py`, `backend/tests/unit/test_storage_provider.py`.
- **Acceptance Criteria:**
  - `alembic upgrade head` creates all tables and indexes in PostgreSQL without error.
  - `TranscriptSegment` table established with sequence, timestamps, speaker_label, text, and metadata.
  - Storage provider generates verifiable presigned `PUT` upload URLs and private read URLs.
  - Repository tests confirm strict tenant/user data isolation.
- **Non-Goals:**
  - No API endpoint routes (except health), no background workers.

---

### PHASE 3 — Authentication + Authorization
- **Objective:** Implement JWT authentication verification (asymmetric/JWKS or standard signature validation), extract user identity, and enforce tenant isolation.
- **Dependencies:** Phase 2.
- **Target Components:**
  - `backend/app/core/security.py` (JWT signature verification and token validation).
  - `backend/app/api/deps.py` (`get_current_user` FastAPI dependency).
  - `backend/tests/security/test_jwt_validation.py`, `backend/tests/security/test_tenant_isolation.py`.
- **Acceptance Criteria:**
  - Unauthenticated requests return HTTP 401.
  - Expired or malformed tokens return HTTP 401.
  - Access to another user's meeting/resource returns HTTP 404 (preventing enumeration/IDOR).
  - JWT validation decouples from hard-coded secret assumptions.
- **Non-Goals:**
  - No custom user registration UI (uses Supabase Auth / OIDC).

---

### PHASE 4 — Upload + Ingestion
- **Objective:** Implement meeting creation, direct-to-storage presigned upload authorization, and upload confirmation endpoints.
- **Dependencies:** Phase 3.
- **Target Components:**
  - `backend/app/api/v1/meetings.py` (`POST /api/v1/meetings`, `GET /api/v1/meetings`, `GET /api/v1/meetings/{id}`, `DELETE /api/v1/meetings/{id}`).
  - `backend/app/api/v1/uploads.py` (`POST /api/v1/meetings/{id}/confirm-upload`).
  - `backend/app/services/meeting_service.py`, `backend/app/services/upload_service.py`.
  - `backend/app/schemas/` (Pydantic request/response schemas).
  - `backend/tests/integration/test_upload_flow.py`, `backend/tests/security/test_signed_urls.py`.
- **Acceptance Criteria:**
  - Client can create a meeting, receive a presigned R2 PUT URL, upload directly to private R2 storage, and confirm upload.
  - Large audio files are never routed through FastAPI memory/disk.
  - Deletion lifecycle (`DELETE /api/v1/meetings/{id}`) cascades across storage and database cleanly.
- **Non-Goals:**
  - No background worker execution, no audio transcription.

---

### PHASE 5 — Worker + Job Engine
- **Objective:** Implement the Celery background worker, Redis task transport, renewable lease/heartbeat mechanism in PostgreSQL, resilient state machine, and status polling API.
- **Dependencies:** Phase 4.
- **Target Components:**
  - `backend/app/workers/tasks.py` (Celery task `process_meeting_recording` with late acks and idempotency guards).
  - `backend/app/workers/job_lease.py` (PostgreSQL lease tracker with `worker_id`, `claimed_at`, `lease_expires_at`, `heartbeat_at`, `attempt`).
  - `backend/app/workers/job_state_machine.py` (Enforces valid statuses: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED` and stages: `VALIDATING` through `SAVING`).
  - `backend/app/services/processing_service.py`.
  - `backend/app/api/v1/status.py` (`GET /api/v1/meetings/{id}/status`).
  - `backend/tests/integration/test_celery_tasks.py`, `backend/tests/integration/test_worker_leases.py`.
- **Acceptance Criteria:**
  - Confirmed upload automatically dispatches Celery task via Redis and creates a `ProcessingJob` in PostgreSQL.
  - Celery worker claims job with renewable lease in PostgreSQL, issues periodic heartbeats, updates stages, and releases lease on completion.
  - Crashed worker leases are safely reclaimed upon expiration without arbitrary fixed limits.
  - Task cancellation properly revokes the Celery task and marks the job `CANCELLED`.
- **Non-Goals:**
  - Real transcription or real LLM calls (mock providers used for pipeline engine testing).

---

### PHASE 6 — Media Extraction, Transcription & Diarization
- **Objective:** Implement media inspection and normalization via FFmpeg, speech-to-text transcription via Groq Whisper Large V3 Turbo, speaker turn diarization via pyannote Community-1, and segment timestamp alignment.
- **Dependencies:** Phase 5.
- **Target Components:**
  - `backend/app/services/audio_service.py` (FFmpeg wrapper inspecting headers and normalizing media to 16 kHz mono WAV).
  - `backend/app/providers/transcription/base.py` (`TranscriptionProvider` interface).
  - `backend/app/providers/transcription/groq_whisper_provider.py` (Groq-hosted Whisper Large V3 Turbo).
  - `backend/app/providers/transcription/local_whisper_provider.py` (`faster-whisper` for dev/test).
  - `backend/app/services/diarization_service.py` (pyannote Community-1 wrapper detecting speaker turns).
  - `backend/app/services/alignment_service.py` (Aligns pyannote speaker intervals with Whisper transcript segments).
  - `backend/app/api/v1/transcript.py` (`GET /api/v1/meetings/{id}/transcript`).
  - `backend/tests/unit/test_transcription_service.py`, `backend/tests/integration/test_diarization_alignment.py`.
- **Acceptance Criteria:**
  - Audio recording is fetched from private R2 storage, validated via FFmpeg, transcribed, and diarized.
  - Transcript segments with `speaker_label` (`SPEAKER_00`) are persisted in PostgreSQL.
  - `GET /api/v1/meetings/{id}/transcript` returns ordered segments with speaker labels.
  - Temporary audio scratch files on the worker are completely deleted after processing.
- **Non-Goals:**
  - No LLM analysis, no LangGraph.

---

### PHASE 7 — Meeting Intelligence & Targeted Verification
- **Objective:** Implement `LLMProvider` abstraction, bounded `MeetingAnalysisAgent` (Groq GPT-OSS 120B / 20B), single structured call with bounded hierarchical processing on overflow, and selective Targeted Verification for ambiguous or high-impact claims.
- **Dependencies:** Phase 6.
- **Target Components:**
  - `backend/app/providers/llm/base.py`, `groq_provider.py` (GPT-OSS 120B and 20B), `openai_provider.py`, `mock_provider.py`.
  - `backend/app/agents/meeting_analysis_agent.py` (Pydantic structured schema extraction).
  - `backend/app/agents/verification_agent.py` (Selective targeted verification for flagged claims).
  - `backend/app/prompts/meeting_analysis_prompt.py` (Untrusted transcript delimiters, zero hallucination enforcement).
  - `backend/app/services/analysis_service.py`.
  - `backend/app/api/v1/analysis.py` (`GET /api/v1/meetings/{id}/analysis`).
  - `backend/tests/unit/test_analysis_agent.py`, `backend/tests/unit/test_evidence_validation.py`.
- **Acceptance Criteria:**
  - Structured LLM call extracts executive summary, topics, decisions, action items, risks, and open questions.
  - Bounded hierarchical chunking activates automatically when transcript exceeds model context window.
  - All decisions and action items reference real `TranscriptSegment.id` values.
  - Targeted verification executes only when deterministic checks detect ambiguous or high-impact claims.
  - Unstated fields (owner, due_date) are strictly `null` (zero hallucination).
  - Token counts, estimated cost, and pricing version metadata are persisted in `meeting_analyses`.
- **Non-Goals:**
  - No conversational chat agent, no blanket second critic LLM on every run, no LangGraph supervisor swarms.

---

### PHASE 8 — Frontend
- **Objective:** Implement responsive, typed Next.js 14 web application with meeting dashboard, direct signed upload progress, live status polling, participant speaker mapping, and rich meeting intelligence view with evidence click-through.
- **Dependencies:** Phase 7.
- **Target Components:**
  - `frontend/src/app/` (Next.js 14 App Router: `/`, `/login`, `/dashboard`, `/meetings/new`, `/meetings/[id]`).
  - `frontend/src/api/` (Typed API client and React Query hooks for `/api/v1/` endpoints).
  - `frontend/src/components/` (`TranscriptViewer`, `SpeakerMapper`, `ExecutiveSummary`, `DecisionsList`, `ActionItemsList`, `TopicsList`, `RisksList`, `EvidenceBadge`).
- **Acceptance Criteria:**
  - User can log in, upload media directly to private storage, monitor status, assign speaker names to speaker labels, and view structured meeting intelligence with synchronized transcript segment playback.
  - Clicking evidence badges scrolls to the corresponding transcript segment.
- **Non-Goals:**
  - No chat interface, no document exports.

---

### PHASE 9 — End-to-End Reliability + Security
- **Objective:** Enforce sliding-window rate limiting, untrusted transcript prompt isolation, robust error sanitization, security headers, and comprehensive reliability scenario verification.
- **Dependencies:** Phase 8.
- **Target Components:**
  - Security middlewares, rate limiting decorators, error handling filters.
  - `backend/tests/security/` (IDOR, prompt injection, invalid JWT, corrupted file suites).
  - `backend/tests/integration/test_reliability_scenarios.py` (Worker crashes, database reconnects, storage timeouts).
- **Acceptance Criteria:**
  - Security test suite confirms rate limits and tenant isolation are enforced.
  - Error responses never leak stack traces or internal provider credentials.
  - Reliable recovery from simulated worker and provider failure scenarios.

---

### PHASE 10 — AI & Model Evaluation Suite
- **Objective:** Build an automated evaluation suite against a curated benchmark dataset of meeting transcripts to compare model candidates and measure extraction accuracy, completeness, evidence correctness, and zero hallucination.
- **Dependencies:** Phase 7.
- **Target Components:**
  - `tests/evaluation/datasets/` (`meeting_001/`, `meeting_002/`, etc. with reference audio, transcripts, and expected ground truth).
  - `tests/evaluation/model_benchmarks/` (`test_stt_benchmark.py` evaluating Whisper Turbo vs V3 vs alt, `test_diarization_eval.py` evaluating pyannote DER, `test_llm_benchmark.py` evaluating GPT-OSS 120B vs 20B).
  - `tests/evaluation/evaluator.py` (Deterministic schema, citation, and hallucination calculator).
  - Benchmark evaluation reports.
- **Acceptance Criteria:**
  - 100% precision on zero-hallucination tests (zero phantom owners/deadlines).
  - Empirical report documenting WER, latency, DER, and cost across tested model candidates.
  - Regression harness flags quality drops if model or prompt is updated.

---

### PHASE 11 — Deployment
- **Objective:** Deploy production infrastructure with separate API and Celery Worker container instances, Redis task broker, managed PostgreSQL, Cloudflare R2 private bucket, Next.js frontend, and CI/CD pipelines.
- **Dependencies:** Phase 9 & Phase 10.
- **Target Components:**
  - `Dockerfile.api`, `Dockerfile.worker` (with system FFmpeg), `Dockerfile.frontend`.
  - Deployment manifests (Fly.io / Render / Docker Compose).
  - Production environment configuration and automated CI/CD deployment pipelines.
- **Acceptance Criteria:**
  - Production API and Celery Worker run as distinct scalable container processes.
  - Redis broker transports tasks while PostgreSQL durably retains all state and results.
  - HTTPS, secure CORS, and environment secrets verified in live staging/production.

---

### PHASE 12 — Meeting Q&A (Planned Future Scope)
- **Objective:** Enable conversational Q&A over specific meeting transcripts using PostgreSQL full-text search first, with pgvector semantic retrieval only if justified by benchmark requirements.
- **Dependencies:** Phase 7 & Phase 8.
- **Target Components:**
  - `backend/app/models/chat.py` (`ChatSession`, `ChatMessage`).
  - `backend/app/api/v1/chat.py` (`POST /api/v1/meetings/{id}/chat`).
  - Grounded answer generation with transcript citation links.
- **Acceptance Criteria:**
  - User can ask natural language questions about a meeting and receive grounded answers with transcript timestamp citations.
