# Data Model — Meeting Recording Summarizer

> **Status:** Phase 0 Baseline — Frozen  
> **Database:** PostgreSQL 15+ (via Supabase / Managed PostgreSQL from Day One)  
> **ORM:** SQLAlchemy 2.x (async) with Alembic migrations  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture Team  

---

## Table of Contents

1. [Entity Overview & Implementation Status](#1-entity-overview--implementation-status)
2. [Complete Entity Schema Definitions](#2-complete-entity-schema-definitions)
   - [users](#21-users)
   - [meetings](#22-meetings)
   - [recordings](#23-recordings)
   - [processing_jobs](#24-processing_jobs)
   - [transcripts](#25-transcripts)
   - [transcript_segments](#26-transcript_segments)
   - [meeting_analyses](#27-meeting_analyses)
   - [topics](#28-topics)
   - [decisions](#29-decisions)
   - [action_items](#210-action_items)
   - [risks](#211-risks)
   - [open_questions](#212-open_questions)
   - [chat_sessions & chat_messages (Phase 12 Future)](#213-chatsessions--chatmessages-phase-12-future)
3. [Explicit Domain State Machines](#3-explicit-domain-state-machines)
4. [Evidence Traceability & Timestamp Derivation](#4-evidence-traceability--timestamp-derivation)
5. [Ownership, Tenant Isolation & ID Strategy](#5-ownership-tenant-isolation--id-strategy)
6. [Index Strategy & GIN Array Queries](#6-index-strategy--gin-array-queries)
7. [Retention & Deletion Lifecycle](#7-retention--deletion-lifecycle)
8. [Migration Strategy (Alembic)](#8-migration-strategy-alembic)

---

## 1. Entity Overview & Implementation Status

```text
User (UUID)
 └── Meeting (UUID, user_id, title, status, meeting_date, speaker_mappings)
       ├── Recording (UUID, user_id, storage_key, file_size, duration, status)
       ├── ProcessingJob (UUID, user_id, celery_task_id, status, stage, attempt)
       ├── Transcript (UUID, user_id, provider, diarization_provider, language)
       │    └── TranscriptSegment (UUID, sequence, start, end, speaker_label, speaker, text)
       ├── MeetingAnalysis (UUID, user_id, title, summary, model_name, cost_usd)
       │    ├── Topic (UUID, sequence, title, summary, start_time, end_time)
       │    ├── Decision (UUID, decision_text, confidence, evidence_segment_ids: UUID[])
       │    ├── ActionItem (UUID, action_text, owner, due_date, evidence_segment_ids: UUID[])
       │    ├── Risk (UUID, risk_text, evidence_segment_ids: UUID[])
       │    └── OpenQuestion (UUID, question_text, evidence_segment_ids: UUID[])
       └── ChatSession (UUID, user_id) [Phase 12 Future]
            └── ChatMessage (UUID, role, content, citation_segment_ids)
```

### Capability Classification

| Entity | Implementation Status | Purpose |
|---|---|---|
| `users` | **Implemented (Phase 2/3)** | Authenticated user profile and quota tracking |
| `meetings` | **Implemented (Phase 2/4)** | Parent container and aggregate root for all meeting assets |
| `recordings` | **Implemented (Phase 2/4)** | Object storage metadata and pre-signed upload tracking |
| `processing_jobs` | **Implemented (Phase 2/5)** | Asynchronous queue with renewable worker lease tracking |
| `transcripts` | **Implemented (Phase 2/6)** | Top-level transcription metadata and full-text cache |
| `transcript_segments` | **Implemented (Phase 2/6)** | Relational timestamped utterances; source of truth for evidence |
| `meeting_analyses` | **Implemented (Phase 2/7)** | Synthesized intelligence header, token usage, and cost audit |
| `topics` | **Implemented (Phase 2/7)** | Chronological discussion topics extracted from transcript |
| `decisions` | **Implemented (Phase 2/7)** | Explicit/inferred decisions linked to `source_segment_ids` |
| `action_items` | **Implemented (Phase 2/7)** | Action items with optional owner/date linked to `source_segment_ids` |
| `risks` | **Implemented (Phase 2/7)** | Highlighted risks and concerns linked to `source_segment_ids` |
| `open_questions` | **Implemented (Phase 2/7)** | Unresolved inquiries linked to `source_segment_ids` |
| `chat_sessions` | **Planned Later (Phase 12)** | Conversational Q&A interactive sessions |
| `chat_messages` | **Planned Later (Phase 12)** | Individual conversation messages with citation links |

---

## 2. Complete Entity Schema Definitions

### 2.1 `users`

```sql
CREATE TABLE users (
    id                       UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    email                    TEXT          NOT NULL,
    display_name             TEXT,
    is_active                BOOLEAN       NOT NULL DEFAULT TRUE,
    quota_minutes_per_month  INTEGER,                          -- NULL = system default
    created_at               TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT users_email_unique UNIQUE (email)
);

CREATE INDEX idx_users_email ON users (email);
```

---

### 2.2 `meetings`

```sql
CREATE TYPE meeting_status AS ENUM (
    'CREATED',
    'ACTIVE',
    'DELETING',
    'PURGED'
);

CREATE TABLE meetings (
    id                       UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  UUID           NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title                    TEXT           NOT NULL,
    description              TEXT,
    meeting_date             DATE           NOT NULL DEFAULT CURRENT_DATE,
    status                   meeting_status NOT NULL DEFAULT 'CREATED',
    speaker_mappings         JSONB          NOT NULL DEFAULT '{}', -- Maps "SPEAKER_00" -> "Alice"
    created_at               TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    deleted_at               TIMESTAMPTZ
);

CREATE INDEX idx_meetings_user_id ON meetings (user_id);
CREATE INDEX idx_meetings_status  ON meetings (status);
```

---

### 2.3 `recordings`

```sql
CREATE TYPE recording_status AS ENUM (
    'PRESIGNED',
    'UPLOADED',
    'DELETED'
);

CREATE TABLE recordings (
    id                UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id        UUID             NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id           UUID             NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    storage_key       TEXT             NOT NULL,
    original_filename TEXT             NOT NULL,
    content_type      TEXT             NOT NULL,
    file_size_bytes   BIGINT           NOT NULL,
    sha256_hash       TEXT,
    status            recording_status NOT NULL DEFAULT 'PRESIGNED',
    uploaded_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT NOW(),

    CONSTRAINT recordings_meeting_id_unique UNIQUE (meeting_id)
);

CREATE INDEX idx_recordings_user_id ON recordings (user_id);
```

---

### 2.4 `processing_jobs`

```sql
CREATE TYPE job_status AS ENUM (
    'PENDING',
    'RUNNING',
    'COMPLETED',
    'FAILED',
    'CANCELLED'
);

CREATE TYPE job_stage AS ENUM (
    'CREATED',
    'VALIDATING',
    'EXTRACTING_AUDIO',
    'TRANSCRIBING',
    'DIARIZING',
    'ANALYZING',
    'VERIFYING',
    'SAVING',
    'COMPLETED',
    'FAILED'
);

CREATE TABLE processing_jobs (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id        UUID        NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id           UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    celery_task_id    TEXT,                          -- Celery async task UUID for tracking/revocation
    status            job_status  NOT NULL DEFAULT 'PENDING',
    stage             job_stage   NOT NULL DEFAULT 'CREATED',
    attempt           INTEGER     NOT NULL DEFAULT 0,
    max_attempts      INTEGER     NOT NULL DEFAULT 3,
    error_code        TEXT,
    error_message     TEXT,
    worker_id         TEXT,                          -- Celery worker identifier holding lease
    claimed_at        TIMESTAMPTZ,
    lease_expires_at  TIMESTAMPTZ,                   -- renewable expiration timestamp
    heartbeat_at      TIMESTAMPTZ,                   -- last heartbeat from worker
    enqueued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT processing_jobs_meeting_id_unique UNIQUE (meeting_id)
);

-- Index for looking up jobs by Celery task ID
CREATE INDEX idx_jobs_celery_task_id ON processing_jobs (celery_task_id);

-- Primary index for active job queries and status dashboard
CREATE INDEX idx_jobs_status_stage ON processing_jobs (status, stage);

-- Stale lease recovery index
CREATE INDEX idx_jobs_lease_recovery ON processing_jobs (status, lease_expires_at)
    WHERE status = 'RUNNING';

CREATE INDEX idx_jobs_user_id ON processing_jobs (user_id);
```

---

### 2.5 `transcripts`

```sql
CREATE TABLE transcripts (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id              UUID        NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id                 UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider                TEXT        NOT NULL,   -- e.g. "groq-whisper-turbo", "groq-whisper-v3", "faster-whisper"
    model                   TEXT,
    diarization_provider    TEXT,                   -- e.g. "pyannote-community-1"
    language                TEXT,
    total_duration_seconds  DOUBLE PRECISION,
    segment_count           INTEGER,
    raw_transcript_text     TEXT,                   -- cached concatenated text
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT transcripts_meeting_id_unique UNIQUE (meeting_id)
);

CREATE INDEX idx_transcripts_user_id ON transcripts (user_id);
```

---

### 2.6 `transcript_segments`

```sql
CREATE TABLE transcript_segments (
    id              UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    transcript_id   UUID             NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
    meeting_id      UUID             NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    sequence_index  INTEGER          NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,   -- seconds
    end_time        DOUBLE PRECISION NOT NULL,   -- seconds
    speaker_label   TEXT,                        -- e.g. "SPEAKER_00" from pyannote diarization
    speaker         TEXT,                        -- mapped human name from meetings.speaker_mappings (or NULL)
    text            TEXT             NOT NULL,
    metadata        JSONB,

    CONSTRAINT transcript_segments_sequence_unique UNIQUE (transcript_id, sequence_index)
);

CREATE INDEX idx_segments_transcript_seq   ON transcript_segments (transcript_id, sequence_index ASC);
CREATE INDEX idx_segments_transcript_time  ON transcript_segments (transcript_id, start_time ASC);
CREATE INDEX idx_segments_speaker_label    ON transcript_segments (speaker_label);
CREATE INDEX idx_segments_meeting_id       ON transcript_segments (meeting_id);
```

---

### 2.7 `meeting_analyses`

```sql
CREATE TABLE meeting_analyses (
    id                      UUID          PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id              UUID          NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id                 UUID          NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    provider                TEXT          NOT NULL,   -- e.g. "groq", "openai"
    model                   TEXT          NOT NULL,   -- e.g. "gpt-oss-120b", "gpt-oss-20b"
    title                   TEXT,
    executive_summary       TEXT,
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    total_tokens            INTEGER,
    estimated_cost_usd      DECIMAL(10,6),
    pricing_version         TEXT,                     -- schema version for historical cost audit
    verification_performed  BOOLEAN       NOT NULL DEFAULT FALSE,
    verification_model      TEXT,                     -- model used if targeted verification was triggered
    created_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ   NOT NULL DEFAULT NOW(),

    CONSTRAINT meeting_analyses_meeting_id_unique UNIQUE (meeting_id)
);

CREATE INDEX idx_analyses_user_id    ON meeting_analyses (user_id);
CREATE INDEX idx_analyses_meeting_id ON meeting_analyses (meeting_id);
```

---

### 2.8 `topics`

```sql
CREATE TABLE topics (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id     UUID            NOT NULL REFERENCES meeting_analyses(id) ON DELETE CASCADE,
    meeting_id      UUID            NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    title           TEXT            NOT NULL,
    summary         TEXT,
    sequence_index  INTEGER         NOT NULL,
    start_time      DOUBLE PRECISION,
    end_time        DOUBLE PRECISION
);

CREATE INDEX idx_topics_analysis_id ON topics (analysis_id, sequence_index ASC);
CREATE INDEX idx_topics_meeting_id  ON topics (meeting_id);
```

---

### 2.9 `decisions`

```sql
CREATE TYPE confidence_level AS ENUM ('EXPLICIT', 'INFERRED');

CREATE TABLE decisions (
    id                   UUID             PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id          UUID             NOT NULL REFERENCES meeting_analyses(id) ON DELETE CASCADE,
    meeting_id           UUID             NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    decision_text        TEXT             NOT NULL,
    sequence_index       INTEGER          NOT NULL,
    confidence           confidence_level NOT NULL DEFAULT 'EXPLICIT',
    start_time           DOUBLE PRECISION,
    end_time             DOUBLE PRECISION,
    evidence_segment_ids UUID[]           NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_decisions_analysis_id ON decisions (analysis_id, sequence_index ASC);
CREATE INDEX idx_decisions_meeting_id  ON decisions (meeting_id);
CREATE INDEX idx_decisions_evidence    ON decisions USING GIN (evidence_segment_ids);
```

---

### 2.10 `action_items`

```sql
CREATE TABLE action_items (
    id                   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id          UUID            NOT NULL REFERENCES meeting_analyses(id) ON DELETE CASCADE,
    meeting_id           UUID            NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    action_text          TEXT            NOT NULL,
    owner                TEXT,                        -- NULL if unstated
    due_date             TEXT,                        -- NULL if unstated
    sequence_index       INTEGER         NOT NULL,
    start_time           DOUBLE PRECISION,
    end_time             DOUBLE PRECISION,
    evidence_segment_ids UUID[]          NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_action_items_analysis_id ON action_items (analysis_id, sequence_index ASC);
CREATE INDEX idx_action_items_meeting_id  ON action_items (meeting_id);
CREATE INDEX idx_action_items_evidence    ON action_items USING GIN (evidence_segment_ids);
```

---

### 2.11 `risks`

```sql
CREATE TABLE risks (
    id                   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id          UUID            NOT NULL REFERENCES meeting_analyses(id) ON DELETE CASCADE,
    meeting_id           UUID            NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    risk_text            TEXT            NOT NULL,
    sequence_index       INTEGER         NOT NULL,
    start_time           DOUBLE PRECISION,
    end_time             DOUBLE PRECISION,
    evidence_segment_ids UUID[]          NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_risks_analysis_id ON risks (analysis_id, sequence_index ASC);
CREATE INDEX idx_risks_meeting_id  ON risks (meeting_id);
CREATE INDEX idx_risks_evidence    ON risks USING GIN (evidence_segment_ids);
```

---

### 2.12 `open_questions`

```sql
CREATE TABLE open_questions (
    id                   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_id          UUID            NOT NULL REFERENCES meeting_analyses(id) ON DELETE CASCADE,
    meeting_id           UUID            NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    question_text        TEXT            NOT NULL,
    sequence_index       INTEGER         NOT NULL,
    start_time           DOUBLE PRECISION,
    end_time             DOUBLE PRECISION,
    evidence_segment_ids UUID[]          NOT NULL DEFAULT '{}'
);

CREATE INDEX idx_open_questions_analysis_id ON open_questions (analysis_id, sequence_index ASC);
CREATE INDEX idx_open_questions_meeting_id  ON open_questions (meeting_id);
CREATE INDEX idx_open_questions_evidence    ON open_questions USING GIN (evidence_segment_ids);
```

---

### 2.13 `chat_sessions` & `chat_messages` (Phase 12 Future)

```sql
CREATE TYPE chat_role AS ENUM ('USER', 'ASSISTANT', 'SYSTEM');

CREATE TABLE chat_sessions (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id  UUID        NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    title       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE chat_messages (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id            UUID        NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    meeting_id            UUID        NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    user_id               UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    role                  chat_role   NOT NULL,
    content               TEXT        NOT NULL,
    citation_segment_ids  UUID[]      NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 3. Explicit Domain State Machines

### 3.1 Meeting State Machine
- **Allowed States:** `CREATED`, `ACTIVE`, `DELETING`, `PURGED`
- **Allowed Transitions:**
  - `CREATED` → `ACTIVE` (upload confirmed and processing initiated)
  - `ACTIVE` → `DELETING` (user requested deletion)
  - `DELETING` → `PURGED` (object storage and relational assets purged)
- **Invalid Transitions:** `PURGED` → `ACTIVE`, `DELETING` → `CREATED`
- **Cancellation & Failure:** Deletion requests immediately transition to `DELETING`, blocking normal read queries.

### 3.2 Recording State Machine
- **Allowed States:** `PRESIGNED`, `UPLOADED`, `DELETED`
- **Allowed Transitions:**
  - `PRESIGNED` → `UPLOADED` (client confirms direct upload to storage)
  - `UPLOADED` → `DELETED` (meeting deletion cleans up storage object)
- **Invalid Transitions:** `DELETED` → `UPLOADED`, `PRESIGNED` → `DELETED`

### 3.3 ProcessingJob State Machine
- **Allowed Statuses:** `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`
- **Allowed Stages:** `CREATED`, `VALIDATING`, `EXTRACTING_AUDIO`, `TRANSCRIBING`, `DIARIZING`, `ANALYZING`, `VERIFYING`, `SAVING`, `COMPLETED`, `FAILED`
- **Allowed Transitions:**
  - `PENDING` (CREATED) → `RUNNING` (VALIDATING): Celery worker consumes task from Redis, verifies lease and idempotency
  - `RUNNING` transitions sequentially through pipeline stages:
    - `VALIDATING` → `EXTRACTING_AUDIO` (MIME/size valid, running FFmpeg normalization)
    - `EXTRACTING_AUDIO` → `TRANSCRIBING` (16 kHz mono WAV extracted, invoking Groq Whisper Large V3 Turbo)
    - `TRANSCRIBING` → `DIARIZING` (raw transcript segments received, running pyannote Community-1 diarization)
    - `DIARIZING` → `ANALYZING` (speaker turns aligned to segments and persisted, invoking Groq GPT-OSS 120B / 20B)
    - `ANALYZING` → `VERIFYING` (structured output received; targeted verification invoked if ambiguous claims detected)
    - `VERIFYING` → `SAVING` (evidence validated, saving relational intelligence entities)
    - `SAVING` → `COMPLETED`: all records committed, lease released
  - `RUNNING` (any stage) → `FAILED`: unrecoverable error encountered; if `attempt < max_attempts`, re-enqueued to `PENDING` with exponential backoff
  - `PENDING` | `RUNNING` → `CANCELLED`: meeting deleted or cancellation requested (Celery task revoked)
- **Invalid Transitions:** `COMPLETED` → `PENDING`, `CANCELLED` → `RUNNING`, `COMPLETED` → `RUNNING`

---

## 4. Evidence Traceability & Timestamp Derivation

1. **Relational Traceability:** All decisions, action items, risks, and open questions contain `evidence_segment_ids UUID[]` matching `transcript_segments.id`.
2. **Deterministic Timestamp Derivation:** Timestamps (`start_time`, `end_time`) on analysis entities are **never trusted from LLM generation**. The backend computes `start_time = MIN(segment.start_time)` and `end_time = MAX(segment.end_time)` directly from the referenced `TranscriptSegment` records in PostgreSQL.

---

## 5. Ownership, Tenant Isolation & ID Strategy

- **Primary Keys:** UUIDv4 (`gen_random_uuid()`) on all tables to prevent ID enumeration attacks.
- **Tenant Isolation:** Every table carries `user_id UUID NOT NULL REFERENCES users(id)`. Every repository query enforces `WHERE user_id = :authenticated_user_id`.

---

## 6. Index Strategy & GIN Array Queries

- GIN indexes (`idx_*_evidence`) on `evidence_segment_ids` enable $O(1)$ reverse-lookup queries to find all intelligence items citing a specific transcript segment:
  ```sql
  SELECT * FROM decisions WHERE evidence_segment_ids @> ARRAY[:segment_id::UUID];
  ```

---

## 7. Retention & Deletion Lifecycle

- **Configurable Policy:** Indefinite retention is not assumed. Retention windows are configurable.
- **Cascading Deletion Pipeline:**
  1. `DELETE /api/v1/meetings/{id}` marks meeting `DELETING`.
  2. Worker deletes binary file from Cloudflare R2 using `recordings.storage_key`.
  3. Relational cascade removes `transcripts`, `transcript_segments`, `meeting_analyses`, and child extraction tables.
  4. Final state recorded as `PURGED` or row deleted.

---

## 8. Migration Strategy (Alembic)

- All schema modifications are versioned through forward-only Alembic migrations in `backend/migrations/versions/`.
- Migrations run automatically on startup via `alembic upgrade head`.
