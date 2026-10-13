# REQUIREMENTS.md
## Meeting Recording Summarizer — Authoritative Product Requirements

| Field            | Value                                      |
|------------------|--------------------------------------------|
| Document Version | 1.2.0                                      |
| Status           | Approved & Frozen — Final Baseline         |
| Last Updated     | 2026-10-13                                 |
| Author           | Architecture Team                          |
| Phase            | 0 — Pre-implementation architecture freeze |

> **This document is the PRIMARY SOURCE OF TRUTH for what the product must do.**
> All design, architecture, and implementation documents derive from and reference this file.
> Changes require explicit version bump and changelog entry.

---

## Table of Contents

1. [Product Objective](#1-product-objective)
2. [Target Users](#2-target-users)
3. [User Journeys](#3-user-journeys)
4. [MVP Scope](#4-mvp-scope)
5. [Future Scope](#5-future-scope)
6. [Deferred Architecture & Concrete Triggers](#6-deferred-architecture--concrete-triggers)
7. [Functional Requirements](#7-functional-requirements)
8. [Non-Functional Requirements](#8-non-functional-requirements)
9. [Security Requirements](#9-security-requirements)
10. [Privacy Requirements](#10-privacy-requirements)
11. [AI Behavior & Evidence Requirements](#11-ai-behavior--evidence-requirements)
12. [Storage & Data Architecture Requirements](#12-storage--data-architecture-requirements)
13. [Performance Targets & Classifications](#13-performance-targets--classifications)
14. [Cost Constraints & Token Optimization](#14-cost-constraints--token-optimization)
15. [UX Requirements](#15-ux-requirements)
16. [Deployment & Runtime Architecture](#16-deployment--runtime-architecture)
17. [Reliability Scenarios](#17-reliability-scenarios)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Assumptions and Constraints](#19-assumptions-and-constraints)
20. [Changelog](#20-changelog)

---

## 1. Product Objective

The **Meeting Recording Summarizer** is an agentic web application that transforms raw audio or video meeting recordings into structured, actionable meeting intelligence. A user uploads a meeting file; the system inspects and extracts audio with FFmpeg, transcribes it, runs speaker diarization to label speaker turns, aligns segments, analyzes content using a bounded large language model (LLM) agent, and returns a structured report containing a summary, key topics, decisions, action items, blockers/risks, and open questions — all rigorously attributed to original spoken transcript segments.

### Core Value Proposition

| Pain Point | Solution |
|------------|----------|
| Long meetings are costly to re-watch | Produce a concise, timestamped summary with speaker attribution |
| Action items are buried in conversation | Extract action items with owners and deadlines linked to transcript evidence |
| Meeting context is lost over time | Persist structured meeting history with configurable retention |
| Decisions are undocumented | Surface and attribute key decisions with direct transcript segment links |
| Risk signals go unnoticed | Identify risks, blockers, and open questions with verbatim citations |

### Guiding Principles
1. **Evidenced Intelligence:** Every output the system produces must be evidenced — traceable to a specific `TranscriptSegment.id`. The system must never fabricate information.
2. **Production-First Architecture:** The system is built for cloud production from day one using PostgreSQL, Celery + Redis, private object storage, and strict provider abstractions.

---

## 2. Target Users

### 2.1 Primary Users
- **Individual Professional:** Knowledge worker recording calls, interviews, or 1:1s; needs quick summary, decisions, and action items.
- **Team Lead / Manager:** Manages recurring team syncs (standups, retros, planning); needs structured output with speaker turns and action items.
- **Executive / Decision Maker:** Needs durable meeting records with accurate decision attribution and risk radar.
- **Consultant / Freelancer:** Needs documented client meetings with verifiable source citations.

---

## 3. User Journeys

### 3.1 Journey 1 — New User Registration and Direct Upload

```text
Step 1: User visits the Next.js web application
Step 2: User registers and logs in via Supabase Auth (or standard OIDC)
Step 3: User initiates upload with meeting title and media file (MP3, MP4, M4A, WAV, WEBM, OGG)
Step 4: Browser validates file size (<= 500 MB) and calls POST /api/v1/meetings
Step 5: Backend generates pre-signed PUT URL for private Cloudflare R2 storage
Step 6: Browser uploads file directly to Cloudflare R2 with progress tracking
Step 7: On upload complete, browser calls POST /api/v1/meetings/{id}/confirm-upload
Step 8: Backend verifies stored object via HeadObject and enqueues Celery task via Redis
Step 9: Celery worker downloads audio, normalizes with FFmpeg, transcribes (Whisper Turbo),
        runs diarization (pyannote Community-1), aligns segments, and runs MeetingAnalysisAgent
Step 10: Worker validates schema & evidence references, executes targeted verification if needed,
         persists results to PostgreSQL, and marks job COMPLETED
Step 11: Next.js dashboard status polling redirects to Meeting Intelligence view
```

---

## 4. MVP Scope

The MVP encompasses:
1. **User Authentication & Tenant Isolation:** Secure JWT authentication and strict resource ownership filtering.
2. **Direct Storage Ingestion:** Pre-signed private upload to Cloudflare R2 (S3-compatible).
3. **Decoupled Celery Worker Engine:** Celery task queue with Redis broker; PostgreSQL as authoritative state store.
4. **Media Processing & Transcription:** FFmpeg audio normalization; `TranscriptionProvider` (Groq Whisper Large V3 Turbo candidate).
5. **Speaker Diarization:** `DiarizationProvider` (pyannote Community-1 baseline); transcript segment alignment.
6. **Relational Transcript Persistence:** Ordered `TranscriptSegment` records with sequence numbers, timestamps, and speaker labels.
7. **Structured Meeting Intelligence:** Single bounded `MeetingAnalysisAgent` producing summary, topics, decisions, action items, risks, and open questions with evidence links. Targeted verification for ambiguous claims.
8. **Versioned REST API:** `/api/v1/` contract for meeting lifecycle, uploads, status polling, transcript, and analysis.
9. **Next.js Frontend:** Responsive dashboard with direct upload progress, status polling, speaker mapping, and evidence-linked viewer.

---

## 5. Future Scope

- **Phase 12 / Future:** Conversational Q&A (`ChatSession`, `ChatMessage`) with grounded transcript retrieval.
- **Future:** Multi-user team workspaces, shared recording libraries, and comments.
- **Future:** Calendar integrations (Google Calendar, Outlook) and cloud recording auto-import.

---

## 6. Deferred Architecture & Concrete Triggers

The following technologies are explicitly deferred from the initial MVP:

| Deferred Technology | Reason for Deferral | Concrete Trigger Justifying Inclusion |
|---|---|---|
| **LangGraph** | Linear Python workflow orchestration is sufficient and deterministic | Addition of complex cyclic workflows with human-in-the-loop branching approvals |
| **pgvector / Dedicated Vector DB** | MVP processes full transcripts directly; summarization does not require embeddings | Phase 12 Q&A retrieval proves inadequate with PostgreSQL Full-Text Search |
| **Multi-Agent Swarms** | Multiple uncoordinated agents increase latency, cost, and divergence | Demonstrated requirement for distinct personas debating contradictory meeting assertions |
| **Second Critic LLM on Every Run** | Deterministic Pydantic validation and evidence checking catches errors cheaply | High hallucination rates on high-impact enterprise claims unresolvable by targeted verification |
| **Distributed Tracing Platform** | Single monolith repo with API and Worker; operational overhead unjustified | Extraction into independent multi-repo microservices |
| **Permanent Job-Step History Table** | `ProcessingJob` state fields + structured logs track current step sufficiently | Explicit product requirement for customer-facing historical audit logs of internal step timings |

---

## 7. Functional Requirements

### 7.1 Authentication & Authorization (FR-AUTH)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-AUTH-01 | The system SHALL authenticate users using standard JWT validation (signature, issuer, audience, expiration, subject). | Must |
| FR-AUTH-02 | The backend SHALL enforce strict tenant isolation: every query on meeting data SHALL include `WHERE user_id = :authenticated_user_id`. | Must |
| FR-AUTH-03 | Any attempt to access a resource owned by another user SHALL return HTTP 404 (preventing IDOR enumeration). | Must |

### 7.2 Meeting Management (FR-MEET)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-MEET-01 | Users SHALL be able to create a meeting with a title, optional date, description, and participant hints via `POST /api/v1/meetings`. | Must |
| FR-MEET-02 | Users SHALL be able to list their meetings with pagination via `GET /api/v1/meetings`. | Must |
| FR-MEET-03 | Users SHALL be able to retrieve meeting details via `GET /api/v1/meetings/{id}`. | Must |
| FR-MEET-04 | Users SHALL be able to initiate deletion of a meeting via `DELETE /api/v1/meetings/{id}`, executing a cascading cleanup across object storage and database records. | Must |

### 7.3 Direct Upload & Ingestion (FR-UPLOAD)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-UPLOAD-01 | Upload authorization SHALL be requested via `POST /api/v1/meetings`, returning a pre-signed `PUT` URL for private object storage. | Must |
| FR-UPLOAD-02 | The client SHALL upload media binaries directly to private object storage without streaming through the API server. | Must |
| FR-UPLOAD-03 | Accepted file formats SHALL be: MP3, MP4, M4A, WAV, WEBM, OGG. | Must |
| FR-UPLOAD-04 | Maximum allowed file size SHALL be 500 MB. | Must |
| FR-UPLOAD-05 | After direct upload finishes, the client SHALL call `POST /api/v1/meetings/{id}/confirm-upload` to verify object presence and enqueue the processing job. | Must |

### 7.4 Asynchronous Worker Engine & Celery (FR-JOB)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-JOB-01 | Asynchronous processing SHALL use Celery as the task runner and Redis as the task broker. | Must |
| FR-JOB-02 | PostgreSQL SHALL be the authoritative source of truth for meeting status, attempts, errors, and results. Redis MUST NOT be the sole source of truth. | Must |
| FR-JOB-03 | Celery tasks SHALL configure late acknowledgment (`acks_late=True`, `reject_on_worker_lost=True`) to ensure jobs survive worker crashes. | Must |
| FR-JOB-04 | Job records in PostgreSQL SHALL track: `id`, `meeting_id`, `status`, `stage`, `celery_task_id`, `attempt`, `max_attempts`, `error_code`, `error_message`, `enqueued_at`, `started_at`, `completed_at`. | Must |
| FR-JOB-05 | Worker tasks SHALL be idempotent — re-running an already-processed or partially-processed job SHALL safely resume from the appropriate checkpoint without duplicating completed work. | Must |
| FR-JOB-06 | Transient failures SHALL be retried with exponential backoff up to `max_attempts = 3`. | Must |
| FR-JOB-07 | Job states SHALL follow an explicit state machine (`PENDING` → `TRANSCRIBING` → `DIARIZING` → `ANALYZING` → `COMPLETED` \| `FAILED`). | Must |

### 7.5 Media Processing & Transcription (FR-TRANS)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-TRANS-01 | Audio MUST be inspected, extracted from video containers, and normalized via FFmpeg prior to transcription. | Must |
| FR-TRANS-02 | Transcription SHALL be encapsulated behind `TranscriptionProvider` interface. | Must |
| FR-TRANS-03 | Initial transcription baseline SHALL be Groq-hosted Whisper Large V3 Turbo, evaluated against Whisper Large V3 and a cloud alternative. | Must |
| FR-TRANS-04 | Transcription output SHALL produce timestamped segments with sequence numbers. | Must |
| FR-TRANS-05 | Large audio files (> 25MB or > 1 hour) SHALL be chunked where provider limits require it. | Must |

### 7.6 Speaker Diarization (FR-DIAR)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-DIAR-01 | Speaker diarization SHALL be encapsulated behind `DiarizationProvider` interface. | Must |
| FR-DIAR-02 | Initial diarization baseline SHALL be pyannote Community-1 (subject to license/access verification and evaluation). | Must |
| FR-DIAR-03 | Diarization output SHALL identify speaker turns with anonymous speaker labels (e.g. `SPEAKER_00`). | Must |
| FR-DIAR-04 | The system SHALL align word/segment-level transcript timestamps with diarization intervals to attribute text to speakers. | Must |
| FR-DIAR-05 | Speaker labels SHALL be stored separately from user-assigned real participant names. | Must |

### 7.7 Meeting Intelligence (FR-ANALYSIS)

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-ANALYSIS-01 | Intelligence extraction SHALL be performed by `MeetingAnalysisAgent` utilizing `LLMProvider` (evaluating GPT-OSS 120B quality candidate and GPT-OSS 20B low-cost candidate via Groq). | Must |
| FR-ANALYSIS-02 | When transcript fits model context, extraction SHALL execute via a single structured LLM call. | Must |
| FR-ANALYSIS-03 | When transcript overflows model context, system SHALL execute bounded hierarchical processing (chunks → compact facts → synthesis). | Must |
| FR-ANALYSIS-04 | The agent output SHALL be strictly validated against the Pydantic `MeetingAnalysis` schema. | Must |
| FR-ANALYSIS-05 | Every extracted decision, action item, risk, and open question SHALL include `source_segment_ids: list[UUID]` referencing valid `TranscriptSegment.id` values. | Must |
| FR-ANALYSIS-06 | Backend logic SHALL derive timestamps deterministically from referenced `TranscriptSegment` records; LLM timestamps are never trusted as authoritative. | Must |
| FR-ANALYSIS-07 | Zero Hallucination Rule: Unmentioned action item owners or due dates SHALL be set to `null` or empty collections. | Must |
| FR-ANALYSIS-08 | Targeted Verification: A secondary targeted model call SHALL be invoked only when needed to verify ambiguous, unsupported, or high-impact claims. | Must |

---

## 8. Non-Functional Requirements

- **NFR-01 Security First:** Zero plaintext secrets in version control; private storage buckets with short-lived presigned URLs.
- **NFR-02 Reliability:** Crash-resilient background processing with Celery late acks, Redis broker, and PostgreSQL state reconciliation.
- **NFR-03 Maintainability:** 100% strict type hints in Python and TypeScript; strict separation between routes, services, repositories, and providers.
- **NFR-04 Cost Efficiency:** Sub-cent operational cost per standard meeting using high-throughput providers and zero egress storage.

---

## 9. Security Requirements

- **SEC-01 JWT Validation:** Decoupled signature verification without hardcoded legacy shared secret assumptions.
- **SEC-02 Tenant Isolation:** SQL-level ownership filtering on all data entities.
- **SEC-03 Untrusted Transcript Prompt Delimiters:** System prompts enforce strict XML/markdown delimiter boundaries to prevent prompt injection from meeting dialogue.
- **SEC-04 Private Media Storage:** No public read access to Cloudflare R2 / S3 buckets.
- **SEC-05 Log Sanitization:** Server logs redact API keys, JWTs, signed URLs, and full transcript texts.

---

## 10. Privacy Requirements

- **PRIV-01 Data Minimization:** Collect only necessary metadata and media required for transcription and analysis.
- **PRIV-02 Configurable Retention:** Data is not promised indefinite retention; retention policies allow automated purging of stale media.
- **PRIV-03 Deterministic Deletion:** `DELETE /api/v1/meetings/{id}` executes complete erasure across storage objects, transcript segments, and analysis records.
- **PRIV-04 Compliance Notes Separation:** Legal and compliance considerations are documented in `docs/LEGAL_COMPLIANCE_NOTES.md` and explicitly disclaim formal legal advice.

---

## 11. AI Behavior & Evidence Requirements

1. **Deterministic Schema Adherence:** All LLM outputs must validate against Pydantic schema models before database persistence.
2. **First-Class Evidence Citation:** Insights must reference `source_segment_ids`. Missing or fabricated IDs trigger schema validation sanitization.
3. **No Phantom Commitments:** The agent must never infer or fabricate owners, deadlines, or consensus decisions not explicitly spoken in the dialogue.

---

## 12. Storage & Data Architecture Requirements

- **STR-01 PostgreSQL from Day One:** Relational storage for users, meetings, recordings, jobs, transcripts, segments, analysis items, and future chat.
- **STR-02 Replaceable Managed Database:** Supabase or Neon used as infrastructure without code lock-in.
- **STR-03 Private Object Storage:** Cloudflare R2 / S3 via `StorageProvider` interface.
- **STR-04 Persistent Relational Segments:** Transcripts stored in `transcript_segments` table for precise evidence linking, pagination, and future search.

---

## 13. Performance Targets & Classifications

Requirements are classified into three distinct categories:
- **P0 — Mandatory Correctness & Reliability:** Transactional consistency, tenant isolation, zero hallucination, crash recovery, idempotent retries.
- **P1 — Performance Targets (Empirical targets to be validated during benchmarking):**
  - Direct upload initiation: < 1 second.
  - End-to-end processing for a 30-minute recording on cloud infrastructure: Target < 5 minutes.
  - API non-upload endpoint p95 latency: Target < 500ms.
  - Status polling response: Target < 100ms.
- **P2 — Future Optimizations:** Streaming responses for Q&A, WebRTC ingest, multi-region CDN caching.

---

## 14. Cost Constraints & Token Optimization

- Operating target: < $0.10 USD per standard 1-hour meeting recording.
- Principle 1: Never resend unnecessary transcript content.
- Principle 2: Single structured LLM call when context allows; bounded hierarchical chunking only on overflow.
- Principle 3: Cache transcript segments in PostgreSQL; re-running analysis never re-transcribes audio.
- Principle 4: Log token counts, provider metrics, and estimated cost with pricing schema version metadata.
- Principle 5: Avoid redundant verification calls; use targeted verification only when claims are ambiguous.

---

## 15. UX Requirements

- Next.js frontend with drag-and-drop direct upload progress bar.
- Auto-updating processing status via polling without page reloads.
- Collapsible intelligence sections with interactive evidence badges that scroll to source transcript segments.
- Speaker label mapping interface enabling users to map `SPEAKER_00` to participant names.
- Friendly empty states for unstated decisions, action items, or risks.

---

## 16. Deployment & Runtime Architecture

- Separate container images / runtime commands for API (`uvicorn app.main:app`), Celery Worker (`celery -A app.core.celery_app worker -l info`), and Next.js frontend.
- Redis container/service configured as Celery task broker.
- Fully 12-factor configuration using environment variables validated by Pydantic Settings.
- Automated database migrations via Alembic on startup.

---

## 17. Reliability Scenarios

| Scenario ID | Failure Event | Expected Resilient Behavior |
|---|---|---|
| **RS-01** | Direct upload network stall | Browser displays retry option; meeting remains in `PENDING` state until confirmed. |
| **RS-02** | Celery worker crashes during transcription | `acks_late=True` and `reject_on_worker_lost=True` ensure Celery task is requeued; reconciliation script verifies DB status. |
| **RS-03** | LLM provider 429 rate limit | Worker catches error, executes exponential backoff, and routes to fallback provider if quota exhausted. |
| **RS-04** | Transcript overflows LLM context | Pipeline activates bounded hierarchical chunking and synthesis automatically. |
| **RS-05** | Malformed LLM JSON output | Schema validation fails; worker retries generation with strict repair prompt up to retry limit. |
| **RS-06** | User deletes meeting while processing | Status set to `DELETING`; worker task detects cancellation and terminates execution cleanly. |
| **RS-07** | Redis broker temporarily unavailable | Celery retries broker connection; PostgreSQL retains durable record of job state. |

---

## 18. Acceptance Criteria

- **AC-01:** Complete end-to-end flow: register → direct upload to R2 → Celery transcription & diarization → analysis extraction → evidence-linked dashboard display.
- **AC-02:** Strict tenant isolation: User A cannot retrieve or mutate User B's meetings (HTTP 404).
- **AC-03:** Zero hallucination verified on test suite: missing owners/dates evaluate to `null`.
- **AC-04:** Celery crash recovery verified: killed worker tasks are requeued and resume safely.
- **AC-05:** Deletion lifecycle verified: deleting a meeting cascades across object storage and all database tables.

---

## 19. Assumptions and Constraints

- **C-01:** PostgreSQL is the mandatory production database from Day One; SQLite is permitted only as an optional local unit test convenience.
- **C-02:** Monolithic repository with decoupled API and Celery Worker runtime roles.
- **C-03:** All external integrations (LLM, transcription, diarization, storage) are isolated behind provider abstract interfaces.
- **C-04:** API versioning strictly enforced under `/api/v1/`.

---

## 20. Changelog

| Version | Date | Author | Summary |
|---------|------|--------|---------|
| 1.0.0 | 2026-10-09 | Architecture Team | Initial draft |
| 1.1.0 | 2026-10-09 | Architecture Team | Phase 0 Freeze: Corrected direct upload flow, decoupled worker, relational transcript segments, hierarchical LLM overflow handling, evidence traceability. |
| 1.2.0 | 2026-10-13 | Architecture Team | Final Planning Update: Incorporated Next.js frontend, Celery + Redis background processing, FFmpeg media processing, Groq Whisper Large V3 Turbo transcription baseline, pyannote Community-1 diarization baseline, GPT-OSS 120B/20B analysis candidates, targeted verification, and explicit architecture deferrals. |
