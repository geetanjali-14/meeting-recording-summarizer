# Architecture Decision Records (ADR Log)

This document records the foundational architectural decisions made for the **Meeting Recording Summarizer Agentic Web Application**.

---

## ADR-001: PostgreSQL as the Mandatory Production Database
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Use PostgreSQL as the primary production database from Day One. Recommended initial managed provider is Supabase PostgreSQL.
- **Context:** The application requires reliable relational storage for users, meetings, transcript segments, structured intelligence, and authoritative job status tracking.
- **Alternatives Considered:** SQLite, MySQL/MariaDB, MongoDB, DynamoDB.
- **Rationale:** PostgreSQL provides robust ACID transactions, native JSONB support, array datatypes (`UUID[]` for evidence linking), and reliable foreign key cascades.
- **Consequences:** All database models and migrations use SQLAlchemy 2.0 and Alembic from Phase 1 onward. Access is encapsulated in a repository layer so PostgreSQL remains provider-agnostic. PostgreSQL is the authoritative source of truth for all application state, attempts, and processing outcomes.

---

## ADR-002: Rejection of SQLite for Production
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** SQLite is strictly prohibited in production and staging environments. SQLite is permitted only as an optional local unit test convenience where PostgreSQL is unavailable; all integration tests must run against real PostgreSQL.
- **Context:** SQLite has single-writer locks, lacks native array types, and cannot be accessed across horizontally scaled container instances.
- **Alternatives Considered:** Using SQLite locally and PostgreSQL in production.
- **Rationale:** Environment divergence causes subtle schema and transaction bugs that emerge only after deployment.
- **Consequences:** Any pull request attempting to use SQLite in production configuration will be rejected.

---

## ADR-003: Cloudflare R2 as Primary Object Storage via S3-Compatible Abstraction
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Use Cloudflare R2 as the initial object storage backend, accessed via standard S3-compatible API contracts (`StorageProvider`).
- **Context:** Meeting audio/video files are large binaries (up to 500MB) that must not reside on ephemeral web servers.
- **Alternatives Considered:** AWS S3, Google Cloud Storage, Supabase Storage, local disk.
- **Rationale:** Cloudflare R2 features **zero egress fees**, generous storage, and standard S3 API compatibility via `boto3`.
- **Consequences:** Direct frontend-to-storage uploads use presigned `PUT` URLs; files are never buffered in web server memory or streamed through FastAPI.

---

## ADR-004: Strict Provider Abstraction for AI, Transcription, and Storage
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** All external capabilities (LLMs, Speech-to-Text, Speaker Diarization, Object Storage) must be encapsulated behind abstract interfaces (`LLMProvider`, `TranscriptionProvider`, `DiarizationProvider`, `StorageProvider`).
- **Context:** AI APIs evolve rapidly, and provider pricing/rate limits fluctuate frequently.
- **Alternatives Considered:** Directly importing vendor SDKs in service code.
- **Rationale:** Decoupling ensures vendor independence and simplifies unit testing via mock providers.
- **Consequences:** Application and agent logic depend strictly on abstract contracts; concrete providers are instantiated via a factory based on validated settings.

---

## ADR-005: LLM Provider Strategy — GPT-OSS Candidates & Targeted Verification
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Route LLM calls through `LLMProvider`, evaluating **GPT-OSS 120B via Groq** as the quality-first candidate and **GPT-OSS 20B via Groq** as the lower-cost candidate. Commercial models (OpenAI, Anthropic) remain pluggable alternatives.
- **Context:** Meeting intelligence requires high structured schema adherence, factual accuracy, and low latency while controlling operational token costs.
- **Alternatives Considered:** Hardcoding proprietary LLM SDKs; multiple uncoordinated agents.
- **Rationale:** Provider abstraction enables instant switching or fallback without altering business logic. GPT-OSS 120B provides deep reasoning for complex discussions, while GPT-OSS 20B offers a fast, economical path.
- **Consequences:** Default configuration targets Groq-hosted open weights models. Targeted verification model calls are invoked only when needed for ambiguous, unsupported, or high-impact claims.

---

## ADR-006: Transcription Provider Strategy — Groq-Hosted Whisper Large V3 Turbo Baseline
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Abstract transcription behind `TranscriptionProvider`, selecting **Groq-hosted Whisper Large V3 Turbo** as the initial baseline candidate, subject to benchmark evaluation against **Whisper Large V3** and at least one suitable alternative (e.g. Deepgram Nova-2 or hosted Whisper API).
- **Context:** Meeting audio transcription requires low word error rate (WER), precise segment timestamps, and sustainable per-hour processing costs.
- **Alternatives Considered:** Self-hosted Whisper on GPU; AssemblyAI; Deepgram exclusively.
- **Rationale:** Whisper Large V3 Turbo on Groq provides sub-minute transcription speeds with strong timestamp fidelity at low cost, while the provider abstraction prevents vendor lock-in.
- **Consequences:** `TRANSCRIPTION_PROVIDER` environment variable toggles the active implementation. Large recordings are chunked where provider limits require it.

---

## ADR-007: Celery + Redis for Background Processing with PostgreSQL as Authoritative Store
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Implement asynchronous background task distribution using **Celery** with **Redis** as the task broker. **PostgreSQL** remains the authoritative source of truth for all meeting metadata, processing status, attempt counts, and results.
- **Context:** Meeting transcription and intelligence extraction are long-running I/O and compute pipelines (1–5 minutes) that must not block synchronous HTTP requests.
- **Alternatives Considered:** In-process asyncio background tasks inside FastAPI; raw PostgreSQL `FOR UPDATE SKIP LOCKED` custom queue; AWS SQS / Temporal.
- **Rationale:** Celery + Redis provides production-grade task dispatch, worker prefetching controls, mature retry management, and horizontal worker scalability. Redis transports tasks; PostgreSQL enforces durable state and crash reconciliation.
- **Consequences:** Celery tasks use late acknowledgment (`acks_late=True`, `reject_on_worker_lost=True`) and explicit worker idempotency checks against PostgreSQL. API and Worker run as separate runtime container processes.

---

## ADR-008: Structured Intelligence Extraction & Large Context Strategy
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Use a single bounded `MeetingAnalysisAgent` that issues a single structured LLM call when the transcript fits the model context window. When the transcript exceeds context limits, execute bounded hierarchical processing (chunks → compact intermediate facts → final synthesis). Targeted verification is used only for high-impact or ambiguous claims.
- **Context:** Multi-call agent pipelines (separate Summary, Decision, Action Item, and Critic agents) multiply latency and token costs.
- **Alternatives Considered:** Multi-agent supervisor/critic loops; vector RAG summarization.
- **Rationale:** A single structured call guided by strict Pydantic schemas captures interrelated context accurately and economically.
- **Consequences:** Zero multi-agent loop overhead; deterministic Python code handles orchestration and validation.

---

## ADR-009: Next.js + TypeScript + Tailwind CSS for Frontend
- **Date:** 2026-10-09 (Updated 2026-10-13)
- **Status:** Accepted
- **Decision:** Build the web application and meeting dashboard using **Next.js**, **TypeScript** (strict mode), and **Tailwind CSS**.
- **Context:** A modern, type-safe, responsive web dashboard is required for meeting upload, direct storage ingestion progress, status monitoring, and intelligence visualization.
- **Alternatives Considered:** Vite + React SPA; Vue.js / Nuxt; SvelteKit.
- **Rationale:** Next.js provides robust server-side rendering, routing, API route flexibility, and rapid component development with strong TypeScript integration.
- **Consequences:** Frontend is deployed as a standalone Next.js service (e.g. on Vercel or containerized Docker).

---

## ADR-010: Standard JWT Authentication & Signature Verification
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Use standard JWT verification (validating signature, issuer, audience, expiration, subject/user identity, and JWKS/public keys where applicable) for Supabase Auth / OIDC tokens.
- **Context:** Need secure user identity verification decoupled from legacy hard-coded HS256 secret assumptions.
- **Rationale:** Decouples authentication verification from vendor-specific SDKs and supports standard asymmetric signing keys.
- **Consequences:** Every protected backend endpoint validates JWTs and enforces strict tenant ownership checks on all resources (`WHERE user_id = :user_id`).

---

## ADR-011: Deferral of Vector Database in MVP
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Do NOT deploy a vector database (Qdrant, Pinecone, pgvector) in the MVP phase.
- **Context:** Summarization and intelligence extraction process the full transcript directly. Conversational Q&A is a Phase 12 feature.
- **Rationale:** Prematurely adding vector indexing introduces unnecessary compute and infrastructure cost. PostgreSQL Full-Text Search will be evaluated first for Q&A.
- **Consequences:** No vector embeddings or vector stores will be configured in Phases 1–11.

---

## ADR-012: UUIDv4 Primary Keys Across All Entities
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** All database tables use UUIDv4 (`gen_random_uuid()`) primary keys.
- **Context:** Sequential integer IDs allow enumeration attacks and leak business volume metrics.
- **Alternatives Considered:** Auto-incrementing BigInt, ULID, NanoID.
- **Rationale:** UUIDs prevent ID guessing attacks and allow client-side or worker-side ID pre-generation.
- **Consequences:** All API URLs and foreign keys use UUID strings.

---

## ADR-013: API Versioning via `/api/v1/` from Day One
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Mount all application endpoints under `/api/v1/`.
- **Context:** Unversioned APIs create severe backward-compatibility friction during mobile app or public API rollouts.
- **Consequences:** All FastAPI routers are mounted with the `/api/v1` prefix.

---

## ADR-014: Mandatory Evidence Traceability for All AI Insights
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Every extracted decision, action item, risk, and open question must reference supporting transcript segment IDs (`source_segment_ids`). Timestamps are derived deterministically by the backend from segments, not from LLM hallucinations.
- **Context:** Users must be able to verify AI assertions against the verbatim source conversation.
- **Consequences:** The analysis schema strictly mandates `source_segment_ids`; items with fabricated or invalid segment IDs are rejected or sanitized.

---

## ADR-015: Null Preference over Guessed Information (Zero Hallucination)
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** When metadata such as action item owners or deadlines are not stated verbatim, they must be set to `null` or empty collections.
- **Context:** Hallucinated owners or fake deadlines cause serious coordination errors in organizations.
- **Consequences:** Analysis prompt instructions explicitly state: *"Never invent an owner or due date. If not explicitly said, set to null."*

---

## ADR-016: Local Filesystem Prohibited for Production Persistence
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Ephemeral container filesystems must never be used for persistent file storage.
- **Context:** Container restarts or horizontal scaling will cause data loss if files are saved to local disks.
- **Consequences:** All binary uploads go directly to Cloudflare R2; local file storage is strictly restricted to local development/testing.

---

## ADR-017: Managed Services as Replaceable Infrastructure, Not Code Dependencies
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** The backend interacts with Supabase and Cloudflare strictly via standard PostgreSQL connection strings (SQLAlchemy) and S3-compatible APIs (Boto3).
- **Context:** Prevents hard vendor lock-in to proprietary client libraries.
- **Consequences:** The backend codebase has zero imports of `supabase-py` and can run on any vanilla PostgreSQL cluster.

---

## ADR-018: Centralized Validated Configuration via Pydantic Settings
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** All environment configuration is loaded, validated, and typed via Pydantic `BaseSettings` on application startup and injected via FastAPI dependencies.
- **Context:** Direct calls to `os.environ` across business logic create brittle failure modes and silent configuration bugs.
- **Consequences:** Business logic and services never read `os.environ` directly.

---

## ADR-019: Configurable Retention and Deterministic Deletion Lifecycle
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** Media files and transcripts do not carry an indefinite retention promise by default. Deletion is executed via a deterministic multi-step lifecycle (`DELETING` → storage purge → DB cascade → tombstone).
- **Context:** Complying with data-minimization principles and operational cost control requires clean erasure guarantees.
- **Consequences:** `DELETE /api/v1/meetings/{id}` blocks normal read access immediately and purges binary and relational assets with retry and error logging.

---

## ADR-020: Untrusted Transcript Prompt Isolation
- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision:** All transcript text passed to LLMs is treated as untrusted data and strictly isolated using unambiguous structural delimiters.
- **Context:** Meeting dialogue can contain adversarial instructions (prompt injection) aimed at overriding extraction rules.
- **Consequences:** System prompts define rigid XML/markdown delimiter boundaries; transcript content is never interpreted as execution instructions.

---

## ADR-021: Speaker Diarization Baseline via pyannote Community-1
- **Date:** 2026-10-13
- **Status:** Accepted
- **Decision:** Use **pyannote Community-1** as the initial baseline for speaker diarization (subject to HuggingFace license/access verification and evaluation), with a replaceable `DiarizationProvider` abstraction.
- **Context:** Users need to know who said what without manual labeling. Diarization detects speaker turns and assigns speaker labels (`SPEAKER_00`, `SPEAKER_01`).
- **Alternatives Considered:** Hosted diarization (AssemblyAI / Deepgram); PyAnnote commercial tier; Whisper internal diarization hacks.
- **Rationale:** pyannote Community-1 provides strong benchmarked diarization accuracy. The provider interface enables seamless substitution if cloud hosted diarization is chosen later.
- **Consequences:** Diarization outputs speaker labels, which are aligned with timestamped transcript segments. Speaker labels are stored separately from user-assigned participant names.

---

## ADR-022: Media Processing via FFmpeg
- **Date:** 2026-10-13
- **Status:** Accepted
- **Decision:** Use **FFmpeg** in worker containers for inspecting media files, extracting audio from video containers, and normalizing sample rates/channels prior to transcription and diarization.
- **Context:** Users upload varied audio and video formats (MP4, WEBM, WAV, M4A, MP3). Transcription and diarization engines require standardized audio streams.
- **Alternatives Considered:** Native Python audio decoders (pydub, soundfile).
- **Rationale:** FFmpeg is the industry standard for media inspection, transcoding, and stream normalization with minimal compute overhead.
- **Consequences:** Worker container images include FFmpeg; audio extraction is executed deterministically in Python subprocesses.

---

## ADR-023: Explicit Deferral of Complex Infrastructure
- **Date:** 2026-10-13
- **Status:** Accepted
- **Decision:** Explicitly defer the following technologies until concrete requirements demand them:
  1. **LangGraph:** Defer until non-linear cyclic workflows with human-in-the-loop approvals are required. Python orchestration is sufficient for initial linear pipelines.
  2. **pgvector / Vector Database:** Defer until Phase 12 Q&A retrieval proves inadequate with PostgreSQL Full-Text Search.
  3. **Multi-agent LLM Swarms:** Defer; a single structured analysis agent with targeted verification avoids multi-agent latency, cost, and divergence.
  4. **Second Critic LLM on Every Run:** Defer; use deterministic Pydantic schema validation and evidence checks, reserving targeted verification model calls for ambiguous/high-impact claims.
  5. **Distributed Tracing Infrastructure:** Defer until microservice extraction; structured JSON logging with `request_id` correlation is sufficient.
  6. **Permanent Job-Step History Table:** Defer; `ProcessingJob` state fields and structured logs track current step without table bloat.
- **Rationale:** Avoid discovering architecture while debugging, and do not introduce speculative infrastructure without concrete requirements.
