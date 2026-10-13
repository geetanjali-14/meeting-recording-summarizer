# Requirements & Architecture Traceability Matrix

> **Document Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture Team  

---

## 1. Overview

This matrix establishes end-to-end traceability across requirements, architectural decisions, data/API contracts, implementation phases, and test/evaluation suites. It prevents feature drift and ensures all technical decisions remain grounded in explicit system requirements.

---

## 2. Traceability Matrix

| Requirement ID | Requirement Summary | Architectural Decision (ADR / Doc) | Data & API Contract | Target Phase | Verification / Test Suite |
|---|---|---|---|---|---|
| **REQ-CORE-01** | Production-First Architecture | ADR-001, ADR-002, ADR-016 | PostgreSQL relational schema, no local disk persistence in prod | Phase 1 & 2 | Integration tests with PostgreSQL container, CI environment guards |
| **REQ-CORE-02** | Secure Direct Upload to Private Storage | ADR-003, ADR-016 (`ARCHITECTURE.md` §3) | `POST /api/v1/meetings` (returns signed URL), `POST /api/v1/meetings/{id}/confirm-upload` | Phase 4 | `tests/integration/test_upload_flow.py`, `tests/security/test_signed_urls.py` |
| **REQ-CORE-03** | Asynchronous Celery + Redis Worker Engine | ADR-007 (`ARCHITECTURE.md` §4) | Celery task (`celery_task_id`), Redis broker, PostgreSQL authoritative state (`worker_id`, `lease_expires_at`, `heartbeat_at`) | Phase 5 | `tests/integration/test_celery_tasks.py`, `tests/integration/test_worker_leases.py` |
| **REQ-CORE-04** | Pluggable Media, Transcription & Diarization | ADR-004, ADR-006, ADR-021, ADR-022 (`ARCHITECTURE.md` §5) | FFmpeg audio normalization, Groq Whisper Large V3 Turbo, pyannote Community-1 diarization | Phase 6 | `tests/unit/test_transcription_provider.py`, `tests/integration/test_diarization_alignment.py` |
| **REQ-CORE-05** | Structured Meeting Intelligence & Targeted Verification | ADR-005, ADR-008 (`AGENT_DESIGN.md`) | Groq GPT-OSS 120B / 20B, Bounded hierarchical processing, Targeted Verification Agent | Phase 7 | `tests/unit/test_agent_schema.py`, `tests/evaluation/` benchmark suites |
| **REQ-CORE-06** | Evidence & Traceability Linking | ADR-014 (`DATA_MODEL.md`, `AGENT_DESIGN.md`) | `TranscriptSegment.id` referenced in `Decision.evidence_segment_ids`, `ActionItem.evidence_segment_ids`, etc. | Phase 7 | `tests/unit/test_evidence_validation.py`, `tests/evaluation/` citation check |
| **REQ-CORE-07** | Zero-Hallucination & Null Preference | ADR-015 (`AGENT_DESIGN.md`) | Schema fields `owner: Optional[str]`, `due_date: Optional[str]`; strict prompt delimiters | Phase 7 | `tests/evaluation/datasets/` null-owner test cases |
| **REQ-CORE-08** | Persistent Relational Transcript Segments | ADR-014, ADR-021 (`DATA_MODEL.md`) | `TranscriptSegment` table (`sequence_index`, `start_time`, `end_time`, `speaker_label`, `speaker`, `text`) | Phase 2 & 6 | `tests/integration/test_transcript_segments.py` |
| **REQ-CORE-09** | Authentication & Asymmetric Token Verification | ADR-010 (`SECURITY.md`) | Standard JWT signature/JWKS validation via `auth_service`, `user_id` extraction | Phase 3 | `tests/security/test_jwt_validation.py` |
| **REQ-CORE-10** | Tenant Isolation & IDOR Protection | ADR-010, ADR-012 (`SECURITY.md`) | UUIDv4 primary keys, SQL ownership filters (`WHERE user_id = :user_id`) | Phase 3 | `tests/security/test_tenant_isolation.py` |
| **REQ-CORE-11** | Configurable Retention & Deletion Lifecycle | ADR-016 (`PRIVACY.md`, `DATA_MODEL.md`) | `DELETE /api/v1/meetings/{id}`; Deletion state machine (`DELETING` → storage → DB → tombstone) | Phase 2 & 4 | `tests/integration/test_deletion_lifecycle.py` |
| **REQ-CORE-12** | Centralized Validated Configuration | `DEVELOPMENT_RULES.md` Rule 1 | Pydantic `Settings` model injected via FastAPI dependencies; zero direct `os.environ` | Phase 1 | `tests/unit/test_config.py` |
| **REQ-CORE-13** | Cost Observability & Token Metrics | `COST_CONTROL.md`, `OBSERVABILITY.md` | Structured audit logging (`job_id`, `tokens`, `duration`, `cost_estimate`, `pricing_version`) | Phase 5 & 7 | `tests/unit/test_cost_tracking.py` |
| **REQ-CORE-14** | Resilient Error Handling & State Recovery | ADR-007 (`ARCHITECTURE.md` §8) | Explicit state machine transitions, exponential backoff retries, lease reclamation | Phase 5 | `tests/integration/test_job_retry_and_cancellation.py` |
| **REQ-CORE-15** | User Interface & Polling Experience | ADR-009 (`PROJECT_PLAN.md`) | Next.js 14 + TypeScript + Tailwind CSS, `/api/v1/meetings/{id}/status` polling | Phase 8 | `tests/frontend/` Playwright E2E suites |

---

## 3. Maintenance Rule

Whenever a functional requirement is updated, added, or deprecated, this matrix **must** be updated simultaneously to maintain complete synchronization between architectural documents and implementation test suites.

