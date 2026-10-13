# Observability & Monitoring Specification

> **Project:** Meeting Recording Summarizer  
> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture Team  

---

## 1. Observability Philosophy

The Meeting Recording Summarizer application is designed with production-grade observability from Day One. Because meeting recordings contain private, sensitive business and personal conversations, our observability approach strictly follows two foundational rules:

1. **Zero Data Leakage:** Never log raw audio/video payloads, full transcript text, raw LLM prompt inputs containing user transcripts, user API keys, JWT tokens, or presigned storage credentials.
2. **Deterministic Traceability:** Every request, background asynchronous job, provider interaction, and state transition must be correlated end-to-end via unique distributed tracing identifiers (`request_id`, `job_id`, `meeting_id`, `user_id`).
3. **No Unnecessary Step Table Overhead:** Job step tracking is maintained in the `ProcessingJob` record and emitted in structured JSON logs without creating a permanent `job_steps_log` database table for MVP.

---

## 2. Structured Log Format

All logs follow a unified JSON schema emitted to `stdout`/`stderr`:

```json
{
  "timestamp": "2026-10-09T18:05:00.123456Z",
  "level": "INFO",
  "service": "job-worker",
  "environment": "production",
  "request_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "operation": "job.analysis.completed",
  "user_id": "usr_8f9a2b..",
  "meeting_id": "c3d4e5f6-a7b8-4c9d-0e1f-2a3b4c5d6e7f",
  "job_id": "f1e2d3c4-b5a6-4978-8765-43210fedcba9",
  "worker_id": "worker-fly-prod-01",
  "duration_ms": 1420.5,
  "status": "success",
  "error_code": null,
  "provider": "groq",
  "model": "gpt-oss-120b",
  "details": {
    "prompt_tokens": 3420,
    "completion_tokens": 512,
    "total_tokens": 3932,
    "estimated_cost_usd": 0.002422,
    "pricing_version": "2026-10-v1"
  }
}
```

### Log Schema Field Definitions

| Field | Type | Description | Required |
|---|---|---|---|
| `timestamp` | String (ISO-8601 UTC) | Precise event creation timestamp | Yes |
| `level` | String (Enum) | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Yes |
| `service` | String | Subsystem: `backend-api`, `job-worker` | Yes |
| `environment` | String | `development`, `staging`, `production` | Yes |
| `request_id` | String (UUID) | Client or gateway request ID | Yes |
| `operation` | String | Standard operational action (e.g., `job.transcription.completed`) | Yes |
| `user_id` | String | User UUID (masked in diagnostic logs) | Optional |
| `meeting_id` | String (UUID) | Target meeting identifier | Optional |
| `job_id` | String (UUID) | Target background processing job identifier | Optional |
| `worker_id` | String | Worker process identifier | Optional |
| `duration_ms` | Float | Execution time in milliseconds | Optional |
| `status` | String (Enum) | `success`, `failure`, `timeout`, `retry` | Yes |
| `error_code` | String | Machine-readable error code | Optional |
| `provider` | String | External provider (`groq`, `hosted_whisper`, `cloudflare_r2`) | Optional |
| `model` | String | Model identifier (e.g. `gpt-oss-120b`, `whisper-large-v3-turbo`) | Optional |
| `details` | Object | Contextual metadata (token counts, pricing version) | Optional |

---

## 3. Standard Operational Event Catalog

### 3.1 Ingestion & Upload Lifecycle
- `meeting.created`: Initiated new meeting metadata record.
- `upload.presigned_url.generated`: Presigned PUT target generated for client direct upload.
- `upload.confirmed`: Client signaled upload completion, backend validated file existence & content length in R2.
- `upload.validation.failed`: Upload rejected due to invalid MIME type, size overflow (>500MB), or checksum mismatch.

### 3.2 Background Job Pipeline
- `job.created`: Processing job inserted into database queue in `PENDING` status.
- `job.dispatched`: Celery task sent to Redis broker (`celery_task_id`).
- `job.claimed`: Celery worker claimed task from Redis and acquired lease in PostgreSQL.
- `job.heartbeat`: Worker updated `heartbeat_at` and renewed `lease_expires_at`.
- `job.audio_extracted`: Audio track extracted and normalized to 16 kHz mono WAV via FFmpeg.
- `job.transcription.started`: Downloaded audio and initiated transcription via Groq Whisper Large V3 Turbo.
- `job.transcription.completed`: Audio converted to timestamped relational segments in PostgreSQL.
- `job.diarization.started`: Speaker diarization started via pyannote Community-1.
- `job.diarization.completed`: Speaker turns identified and aligned with transcript segments (`speaker_label`).
- `job.analysis.started`: Meeting Analysis Agent invoked with fenced transcript (Groq GPT-OSS 120B / 20B).
- `job.analysis.completed`: Validated Pydantic output produced, tokens counted, cost recorded with `pricing_version`.
- `job.verification.triggered`: Targeted verification invoked for flagged ambiguous/high-impact claim.
- `job.verification.completed`: Targeted verification concluded.
- `job.completed`: All stages succeeded; meeting status transitioned to `ACTIVE`.
- `job.failed`: Terminal job failure; sanitized error saved to `last_error`.
- `job.retry.scheduled`: Transient failure triggered exponential backoff retry.

---

## 4. Tracing & Distributed Correlation

```text
HTTP Client Request (Optional X-Request-ID: <UUID>)
        │
        ▼
FastAPI Middleware (RequestContextMiddleware)
  - Validates existing UUID or generates new RFC-4122 v4 UUID
  - Sets Python contextvars.ContextVar[str] ("request_id")
  - Injects X-Request-ID into HTTP response headers
        │
        ├──► Synchronous DB operations (stamps request_id into audit trails)
        │
        └──► Enqueues Job in processing_jobs & Dispatches Celery Task (passes request_id)
                │
                ▼
Dedicated Celery Worker Process
  - Consumes task from Redis broker
  - Restores request_id into worker context
  - Emits all transcription, diarization & LLM agent logs with original request_id
```

---

## 5. Token Usage, Pricing Versioning & Financial Cost Accounting

### 5.1 Cost Tracking Invariants
- Each LLM analysis record stores `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated_cost_usd`, and `pricing_version`.
- Pricing versioning ensures historical billing records do not shift when underlying vendor prices change.

---

## 6. Health Checks & Probing

The `/api/v1/health` endpoint serves as the unified health check for container orchestrators and monitors.

```json
{
  "status": "healthy",
  "version": "1.1.0",
  "timestamp": "2026-10-09T18:00:00Z"
}
```

---

## 7. Strict Anti-Logging Rules (Prohibitions)

The following items **MUST NEVER BE LOGGED**:
1. **Audio/Video Binary Payloads**
2. **Plaintext Transcripts or Dialogue Segments**
3. **LLM Prompts Containing User Spoken Text**
4. **JWTs, Passwords, or Session Tokens**
5. **Pre-signed Storage URLs (containing HMAC signatures)**
6. **Raw `DATABASE_URL` strings with credentials**
