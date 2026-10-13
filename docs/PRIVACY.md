# PRIVACY.md — Engineering Data Privacy & Handling Practices

> **Project:** Meeting Recording Summarizer  
> **Document Type:** Technical Privacy & Data Handling Specification  
> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Audience:** Engineers, Product Stakeholders, Security Reviewers  
> **Document Owner:** Architecture & Security Team  

---

> [!NOTE]
> **Engineering Scope Notice:** This document describes the technical architecture and data handling mechanisms implemented in code. For regulatory considerations, recording consent notes, and jurisdictional compliance planning, refer to [`docs/LEGAL_COMPLIANCE_NOTES.md`](./LEGAL_COMPLIANCE_NOTES.md). This document does not constitute formal legal advice.

---

## Table of Contents

1. [Engineering Privacy Principles](#1-engineering-privacy-principles)
2. [Data Inventory & Storage Locations](#2-data-inventory--storage-locations)
3. [Third-Party AI & Cloud Provider Handling](#3-third-party-ai--cloud-provider-handling)
4. [Access Control & Tenant Scoping](#4-access-control--tenant-scoping)
5. [Configurable Retention & Deterministic Erasure](#5-configurable-retention--deterministic-erasure)
6. [Logging Hygiene & Redaction](#6-logging-hygiene--redaction)
7. [Local Processing Mode (Air-Gapped Option)](#7-local-processing-mode-air-gapped-option)

---

## 1. Engineering Privacy Principles

1. **Data Minimization:** We collect, store, and transmit only the data strictly required to execute speech-to-text transcription and structured intelligence synthesis.
2. **Untrusted Input Isolation:** Audio and transcript contents are isolated and never used to influence backend execution logic.
3. **No Unbounded Data Accumulation:** Data is subject to configurable retention lifecycles and permanent cascading erasure.
4. **Provider Transparency:** External provider data egress points are explicitly documented and abstracted.

---

## 2. Data Inventory & Storage Locations

| Data Category | Specific Fields | Storage Location | Retention Lifetime | Access Boundary |
|---|---|---|---|---|
| **User Identity** | Email, User ID (UUID), display name | PostgreSQL (`users` table) | Account active lifetime | Authenticated user / System |
| **Media Binaries** | Raw audio/video recordings | Cloudflare R2 (Private bucket) | Configurable / until meeting deletion | Short-lived signed URLs ($\le 15$ min) |
| **Transcript Segments** | Sequence, start/end timestamps, speaker label, verbatim text | PostgreSQL (`transcript_segments` table) | Configurable / until meeting deletion | Authenticated user (`WHERE user_id = :id`) |
| **Meeting Intelligence** | Executive summary, topics, decisions, action items, risks, open questions | PostgreSQL (`meeting_analyses` table) | Configurable / until meeting deletion | Authenticated user (`WHERE user_id = :id`) |
| **Operational Metadata** | Job status, worker ID, execution durations, retry attempts | PostgreSQL (`processing_jobs` table) | 30 days after job completion | System / User status polling |
| **Cost & Token Audit** | Prompt tokens, completion tokens, model name, estimated USD cost, pricing version | PostgreSQL (`meeting_analyses` table) | Linked to analysis lifetime | Authenticated user / Operator |

---

## 3. Third-Party AI & Cloud Provider Handling

The software integrates with external providers via clean abstractions. Data egress is limited to functional processing:

```text
Celery Worker Process
   ├── Audio File (over TLS 1.3) ──► Transcription Provider (Groq Whisper Large V3 Turbo)
   │                                 (Processes audio; returns timestamped segments)
   │
   ├── Audio File (Local/Worker) ──► Diarization Provider (pyannote Community-1)
   │                                 (Detects anonymous speaker turns; zero biometric templates saved)
   │
   └── Text Segments (over TLS 1.3) ──► LLM Provider (Groq GPT-OSS 120B / 20B)
                                       (Processes prompt; returns structured JSON)
```

### Provider & Pipeline Privacy Invariants:
- **Zero Injected PII:** No user account identifiers, email addresses, or billing details are included in prompts sent to LLMs or STT APIs.
- **No Biometric Voiceprints:** Speaker diarization detects local speaker turns within a single meeting (`SPEAKER_00`, `SPEAKER_01`). The system **never** creates, persists, or exports biometric voiceprints or cross-meeting voice identity profiles.
- **Ephemeral Worker Scratch Space:** Media files downloaded by Celery workers to local scratch disk for FFmpeg conversion and diarization are strictly purged immediately upon pipeline completion or error.
- **Ephemeral Task Broker (Redis):** Redis stores transient Celery task identifiers and metadata only. No audio binaries, full transcripts, or sensitive meeting intelligence are durably retained in Redis.
- **Enterprise No-Training Terms:** Production deployments should configure providers whose terms prohibit retaining customer API payloads for model training.

---

## 4. Access Control & Tenant Scoping

- **Cryptographic User Identification:** Users authenticate via JWT tokens. The backend extracts `user_id` from validated claims.
- **Hard Tenant Isolation:** Every database query includes `WHERE user_id = :authenticated_user_id`. Cross-user data leakage is strictly blocked.
- **Private Object Storage:** Audio files in Cloudflare R2 are accessible only via short-lived, HMAC-signed pre-signed URLs generated for the owning user.

---

## 5. Configurable Retention & Deterministic Erasure

The application does **not** assume indefinite data retention:
1. **Configurable Retention:** Operators can configure retention thresholds for raw recordings and completed analyses.
2. **Deletion Lifecycle Pipeline:**
   - User triggers `DELETE /api/v1/meetings/{id}`.
   - Meeting status transitions to `DELETING`, blocking normal API queries.
   - The media file in Cloudflare R2 is deleted via S3 API call.
   - PostgreSQL cascades delete all associated `recordings`, `transcripts`, `transcript_segments`, `meeting_analyses`, `topics`, `decisions`, `action_items`, `risks`, and `open_questions`.
   - The meeting record is purged or marked `PURGED` for audit consistency.

---

## 6. Logging Hygiene & Redaction

To prevent sensitive data leakage into log management systems:
- **Forbidden in Logs:** Plaintext transcripts, full user prompts, raw audio payloads, JWT tokens, API keys, and pre-signed storage URLs.
- **Allowed in Logs:** `request_id`, `user_id` (UUID), `meeting_id` (UUID), `job_id` (UUID), `step`, `duration_ms`, `token_counts`, and structured error codes.

---

## 7. Local Processing Mode (Air-Gapped Option)

For high-privacy environments where zero external network egress is required:
- **Speech-to-Text:** `LocalWhisperProvider` (`faster-whisper`) runs inference locally on CPU/GPU.
- **LLM Reasoning:** `LocalProvider` interfaces with locally hosted models (e.g. Ollama or vLLM).
- **Storage:** MinIO or S3-compatible local instances.
- **Outcome:** Complete end-to-end processing without transmitting any data over the public internet.
