# API Specification — Meeting Recording Summarizer

> **Version:** 1.1.0  
> **Base URL (production):** `https://api.meetingsummarizer.app/api/v1`  
> **Base URL (development):** `http://localhost:8000/api/v1`  
> **Last Updated:** 2026-10-09  
> **Status:** Phase 0 Baseline — Frozen  
> **Document Owner:** Architecture Team  

---

## Table of Contents

1. [Design Principles](#1-design-principles)
2. [Standard Response Envelope](#2-standard-response-envelope)
3. [Authentication & Authorization](#3-authentication--authorization)
4. [Standard Error Codes](#4-standard-error-codes)
5. [Rate Limiting](#5-rate-limiting)
6. [API Versioning Strategy](#6-api-versioning-strategy)
7. [Endpoints Specification](#7-endpoints-specification)
   - 7.1 [Health Probe (`GET /api/v1/health`)](#71-health-probe)
   - 7.2 [Create Meeting & Request Upload URL (`POST /api/v1/meetings`)](#72-create-meeting--request-upload-url)
   - 7.3 [Confirm Direct Upload (`POST /api/v1/meetings/{id}/confirm-upload`)](#73-confirm-direct-upload)
   - 7.4 [List Meetings (`GET /api/v1/meetings`)](#74-list-meetings)
   - 7.5 [Get Meeting Details (`GET /api/v1/meetings/{id}`)](#75-get-meeting-details)
   - 7.6 [Delete Meeting (`DELETE /api/v1/meetings/{id}`)](#76-delete-meeting)
   - 7.7 [Get Processing Status (`GET /api/v1/meetings/{id}/status`)](#77-get-processing-status)
   - 7.8 [Get Transcript Segments (`GET /api/v1/meetings/{id}/transcript`)](#78-get-transcript-segments)
   - 7.9 [Get Meeting Analysis (`GET /api/v1/meetings/{id}/analysis`)](#79-get-meeting-analysis)
   - 7.10 [Interactive Chat (`POST /api/v1/meetings/{id}/chat`) — Planned Future (Phase 12)](#710-interactive-chat--planned-future-phase-12)
   - 7.11 [Export Analysis (`POST /api/v1/meetings/{id}/exports`) — Planned Future](#711-export-analysis--planned-future)
8. [Direct Storage Ingestion Sequence](#8-direct-storage-ingestion-sequence)

---

## 1. Design Principles

| Principle | Specification |
|---|---|
| **API Versioning** | All application routes mounted strictly under `/api/v1/`. |
| **Data Format** | Request and response payloads are strictly `application/json`. Media binaries are uploaded directly from the browser to private object storage via pre-signed `PUT` URLs — never proxied through FastAPI. |
| **Authentication** | All protected endpoints require standard `Authorization: Bearer <JWT>` header. |
| **Tenant Isolation** | The authenticated user's `user_id` is extracted strictly from the validated token. Missing access or querying another user's resource returns HTTP 404 to prevent IDOR enumeration. |
| **Evidence Traceability** | Analysis items (decisions, action items, risks, open questions) link to `evidence_segment_ids: UUID[]`. |
| **Zero Hallucination** | Unmentioned owners or deadlines are returned as `null`. |
| **Request Tracing** | Every request accepts and echoes an `X-Request-ID` UUID header for observability. |

---

## 2. Standard Response Envelope

### 2.1 Success Envelope
```json
{
  "data": { ... },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:00:00Z"
  }
}
```

### 2.2 List Success Envelope
```json
{
  "data": [ ... ],
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:00:00Z",
    "total_count": 14,
    "page": 1,
    "per_page": 20,
    "has_next_page": false
  }
}
```

### 2.3 Error Envelope
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "File size exceeds the 500 MB maximum limit.",
    "details": [
      {
        "field": "file_size_bytes",
        "issue": "must be less than or equal to 524288000"
      }
    ],
    "request_id": "550e8400-e29b-41d4-a716-446655440000"
  }
}
```

---

## 3. Authentication & Authorization

Protected endpoints validate the JWT against configured public keys/JWKS (or verified signature algorithms). Resource access verifies `WHERE user_id = :authenticated_user_id`.

---

## 4. Standard Error Codes

| Code | HTTP Status | Description |
|---|---|---|
| `UNAUTHORIZED` | 401 | Missing, invalid, or expired JWT token |
| `NOT_FOUND` | 404 | Resource does not exist or belongs to another user (IDOR defense) |
| `CONFLICT` | 409 | Resource state does not permit the requested transition |
| `VALIDATION_ERROR` | 422 | Request payload failed Pydantic schema validation |
| `RATE_LIMITED` | 429 | Sliding window rate limit exceeded |
| `STORAGE_ERROR` | 502 | Upstream object storage error |
| `INTERNAL_ERROR` | 500 | Unhandled internal server error (redacted in response) |

---

## 5. Rate Limiting

Rate limits are enforced per authenticated `user_id` using sliding window counters:
- `POST /api/v1/meetings`: 20 requests / hour
- `POST /api/v1/meetings/{id}/confirm-upload`: 20 requests / hour
- `GET /api/v1/meetings/{id}/status`: 300 requests / minute
- General read endpoints: 120 requests / minute

---

## 6. API Versioning Strategy

All endpoints reside under `/api/v1/`. Any breaking schema or authentication change will be introduced via `/api/v2/` with a defined deprecation window.

---

## 7. Endpoints Specification

### 7.1 Health Probe
`GET /api/v1/health`  
- **Auth:** Public
- **Status:** Implemented (Phase 1)
- **Response `200 OK`:**
```json
{
  "status": "healthy",
  "version": "1.1.0",
  "timestamp": "2026-10-09T18:00:00Z"
}
```

---

### 7.2 Create Meeting & Request Upload URL
`POST /api/v1/meetings`  
- **Auth:** Required
- **Status:** Implemented (Phase 4)
- **Request Body:**
```json
{
  "title": "Weekly Sprint Planning",
  "description": "Discussion on Q4 backend refactoring",
  "meeting_date": "2026-10-09",
  "filename": "sprint_planning.mp4",
  "content_type": "video/mp4",
  "file_size_bytes": 145000000
}
```
- **Constraints:**
  - `content_type` must be one of: `audio/mpeg`, `audio/mp4`, `audio/x-m4a`, `audio/wav`, `audio/webm`, `audio/ogg`, `video/mp4`, `video/webm`.
  - `file_size_bytes` must be $\le 524,288,000$ (500 MB).
- **Response `201 Created`:**
```json
{
  "data": {
    "meeting_id": "018e9a4b-c3d2-7f01-ae12-3456789abcde",
    "recording_id": "018e9a4b-d1a2-7f01-be23-456789abcdef",
    "status": "CREATED",
    "upload_url": "https://<account-id>.r2.cloudflarestorage.com/recordings/...?X-Amz-Signature=...",
    "upload_token": "up_tok_987654321",
    "expires_in_seconds": 900
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:00:00Z"
  }
}
```

---

### 7.3 Confirm Direct Upload
`POST /api/v1/meetings/{meeting_id}/confirm-upload`  
- **Auth:** Required
- **Status:** Implemented (Phase 4)
- **Request Body:**
```json
{
  "recording_id": "018e9a4b-d1a2-7f01-be23-456789abcdef",
  "upload_token": "up_tok_987654321"
}
```
- **Response `202 Accepted`:**
```json
{
  "data": {
    "meeting_id": "018e9a4b-c3d2-7f01-ae12-3456789abcde",
    "job_id": "018e9a4b-e3f4-7f01-cf34-567890abcdef",
    "status": "ACTIVE",
    "job_status": "PENDING"
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:02:00Z"
  }
}
```

---

### 7.4 List Meetings
`GET /api/v1/meetings?page=1&per_page=20`  
- **Auth:** Required
- **Status:** Implemented (Phase 4)
- **Response `200 OK`:**
```json
{
  "data": [
    {
      "meeting_id": "018e9a4b-c3d2-7f01-ae12-3456789abcde",
      "title": "Weekly Sprint Planning",
      "meeting_date": "2026-10-09",
      "status": "ACTIVE",
      "created_at": "2026-10-09T18:00:00Z"
    }
  ],
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:05:00Z",
    "total_count": 1,
    "page": 1,
    "per_page": 20,
    "has_next_page": false
  }
}
```

---

### 7.5 Get Meeting Details
`GET /api/v1/meetings/{meeting_id}`  
- **Auth:** Required
- **Status:** Implemented (Phase 4)
- **Response `200 OK`:**
```json
{
  "data": {
    "meeting_id": "018e9a4b-c3d2-7f01-ae12-3456789abcde",
    "title": "Weekly Sprint Planning",
    "description": "Discussion on Q4 backend refactoring",
    "meeting_date": "2026-10-09",
    "status": "ACTIVE",
    "created_at": "2026-10-09T18:00:00Z",
    "recording": {
      "recording_id": "018e9a4b-d1a2-7f01-be23-456789abcdef",
      "filename": "sprint_planning.mp4",
      "content_type": "video/mp4",
      "file_size_bytes": 145000000,
      "status": "UPLOADED"
    },
    "job": {
      "job_id": "018e9a4b-e3f4-7f01-cf34-567890abcdef",
      "status": "COMPLETED",
      "attempt": 1
    }
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:05:00Z"
  }
}
```

---

### 7.6 Delete Meeting
`DELETE /api/v1/meetings/{meeting_id}`  
- **Auth:** Required
- **Status:** Implemented (Phase 4)
- **Response `204 No Content`**

---

### 7.7 Get Processing Status
`GET /api/v1/meetings/{meeting_id}/status`  
- **Auth:** Required
- **Status:** Implemented (Phase 5)
- **Response `200 OK`:**
```json
{
  "data": {
    "meeting_id": "018e9a4b-c3d2-7f01-ae12-3456789abcde",
    "job_id": "018e9a4b-e3f4-7f01-cf34-567890abcdef",
    "celery_task_id": "c7a8b9d0-1234-5678-9abc-def012345678",
    "status": "RUNNING",
    "stage": "ANALYZING",
    "attempt": 1,
    "error_code": null,
    "error_message": null
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:03:00Z"
  }
}
```

---

### 7.8 Get Transcript Segments
`GET /api/v1/meetings/{meeting_id}/transcript`  
- **Auth:** Required
- **Status:** Implemented (Phase 6)
- **Response `200 OK`:**
```json
{
  "data": {
    "transcript_id": "018e9a4c-a1b2-7f01-df45-678901bcdefg",
    "language": "en",
    "total_duration_seconds": 1820.5,
    "segment_count": 2,
    "segments": [
      {
        "segment_id": "018e9a4c-b2c3-7f01-ef56-789012cdefgh",
        "sequence_index": 0,
        "start_time": 0.0,
        "end_time": 4.5,
        "speaker_label": "SPEAKER_00",
        "speaker": "Alice",
        "text": "Let us review the database schema migration plan."
      },
      {
        "segment_id": "018e9a4c-c3d4-7f01-ff67-890123defghi",
        "sequence_index": 1,
        "start_time": 4.8,
        "end_time": 10.2,
        "speaker_label": "SPEAKER_01",
        "speaker": "Bob",
        "text": "Agreed. We will use PostgreSQL from day one with renewable worker leases."
      }
    ]
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:05:00Z"
  }
}
```

---

### 7.9 Get Meeting Analysis
`GET /api/v1/meetings/{meeting_id}/analysis`  
- **Auth:** Required
- **Status:** Implemented (Phase 7)
- **Response `200 OK`:**
```json
{
  "data": {
    "analysis_id": "018e9a4d-d4e5-7f01-gf78-901234efghij",
    "title": "Weekly Sprint Planning — Architecture Review",
    "executive_summary": "The team aligned on PostgreSQL from day one and finalized the decoupled worker architecture with renewable leases.",
    "model": "gpt-oss-120b",
    "estimated_cost_usd": 0.0042,
    "topics": [
      {
        "topic_id": "018e9a4e-1111-7f01-aaaa-111111111111",
        "sequence_index": 0,
        "title": "Database Architecture",
        "summary": "Mandatory PostgreSQL adoption from Phase 1.",
        "start_time": 0.0,
        "end_time": 10.2
      }
    ],
    "decisions": [
      {
        "decision_id": "018e9a4e-2222-7f01-bbbb-222222222222",
        "sequence_index": 0,
        "decision_text": "Adopt PostgreSQL from day one with renewable worker leases.",
        "confidence": "EXPLICIT",
        "start_time": 4.8,
        "end_time": 10.2,
        "evidence_segment_ids": [
          "018e9a4c-c3d4-7f01-ff67-890123defghi"
        ]
      }
    ],
    "action_items": [
      {
        "action_item_id": "018e9a4e-3333-7f01-cccc-333333333333",
        "sequence_index": 0,
        "action_text": "Write initial Alembic migration for transcript_segments table.",
        "owner": null,
        "due_date": null,
        "start_time": 0.0,
        "end_time": 4.5,
        "evidence_segment_ids": [
          "018e9a4c-b2c3-7f01-ef56-789012cdefgh"
        ]
      }
    ],
    "risks": [],
    "open_questions": []
  },
  "meta": {
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp": "2026-10-09T18:05:00Z"
  }
}
```

---

### 7.10 Interactive Chat — Planned Future (Phase 12)
`POST /api/v1/meetings/{meeting_id}/chat`  
- **Status:** Planned Later (Phase 12)

---

### 7.11 Export Analysis — Planned Future
`POST /api/v1/meetings/{meeting_id}/exports`  
- **Status:** Planned Later

---

## 8. Direct Storage Ingestion Sequence

```text
Frontend                    FastAPI API (/api/v1)           Cloudflare R2 Storage
   │                               │                                  │
   │── 1. POST /meetings ─────────►│                                  │
   │   { title, format, size }     │                                  │
   │                               │── 2. Create Meeting & Recording  │
   │                               │── 3. Gen Pre-signed PUT (15m TTL)│
   │◄── 4. 201 Created ────────────│                                  │
   │   { upload_url, token }       │                                  │
   │                               │                                  │
   │── 5. Direct PUT Binary ─────────────────────────────────────────►│
   │   (with client progress bar)  │                                  │
   │◄── 6. HTTP 200 OK ───────────────────────────────────────────────│
   │                               │                                  │
   │── 7. POST /confirm-upload ───►│                                  │
   │   { recording_id, token }     │                                  │
   │                               │── 8. HeadObject Verify ─────────►│
   │                               │◄── 9. Object Confirmed ──────────│
   │                               │── 10. Persist Job & Celery Delay │
   │◄── 11. 202 Accepted ──────────│                                  │
```
