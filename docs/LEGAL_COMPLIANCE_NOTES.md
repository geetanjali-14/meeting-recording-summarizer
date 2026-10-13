# Legal & Compliance Engineering Planning Notes

> **Document Status:** Informational / Planning Baseline  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture & Security Team  

---

> [!IMPORTANT]
> **DISCLAIMER: NOT LEGAL ADVICE**  
> This document contains technical engineering planning notes regarding privacy-by-design architecture, data handling, and regulatory considerations. It is intended solely for technical planning and system design purposes and **does not constitute legal advice or formal compliance certification**. Organizations deploying this software must consult qualified legal counsel to determine applicable compliance obligations (e.g., GDPR, CCPA/CPRA, HIPAA, wiretapping/two-party recording consent statutes) within their specific jurisdictions.

---

## 1. Scope and Engineering Intent

The Meeting Recording Summarizer is designed with privacy-by-design principles to enable data-minimization, secure tenant isolation, configurable retention, and transparent data deletion. This document outlines the technical mechanisms provided by the software to support compliance workflows.

---

## 2. Audio & Video Recording Consent Considerations

Meeting recordings often capture audio and video of multiple participants across different legal jurisdictions:

- **Two-Party / All-Party Consent Jurisdictions:** Several legal jurisdictions require explicit affirmative consent from all meeting participants before any recording may take place.
- **Technical Responsibility:** The software is an analytical processing tool and ingestion engine. It does not automatically capture live meetings or bypass user notification.
- **Operational Recommendation:** Operators and deploying organizations must ensure that recording notices, disclaimers, or calendar announcements are presented to participants before uploading recordings.

---

## 3. Data Privacy & Minimization Mechanisms

The system architecture implements the following technical controls to support data protection principles:

1. **Tenant Isolation:** All data records (`Meeting`, `Recording`, `Transcript`, `MeetingAnalysis`, `ChatSession`) are strictly scoped to the owning authenticated `user_id`. No cross-tenant data leakage is permitted.
2. **Configurable Retention:** Data retention is not indefinite by default. The system supports retention policies to purge stale recordings and transcripts according to organizational policy.
3. **Cryptographic Deletion Lifecycle:** Upon a user delete request (`DELETE /api/v1/meetings/{id}`), the system executes a deterministic deletion pipeline:
   - Sets status to `DELETING` to block standard API read access immediately.
   - Deletes media objects from private object storage (Cloudflare R2 / S3).
   - Deletes relational transcript segments, full transcripts, and analysis records.
   - Cleans associated processing job records and records a tombstone/purged status.
   - Any transient failure during deletion triggers an audit log and retries.
4. **Untrusted Data Isolation:** Transcripts are treated as untrusted user input to prevent prompt injection and untrusted instruction execution.
5. **No Long-Term Secret or Credential Logging:** Authentication tokens, JWTs, signing keys, and pre-signed storage URLs are strictly excluded from server logs and database records.

---

## 4. Third-Party Provider Handling

When integrating external cloud providers (e.g., cloud LLMs, cloud transcription providers, managed databases, or object storage):
- **Data Egress:** Media files and transcript text are transmitted over TLS 1.3 to configured external provider APIs (such as Groq, OpenAI, Cloudflare, or Supabase).
- **Zero Data Training Agreements:** Deployers must verify with their chosen external cloud providers that enterprise API terms prohibit training models on customer transcript payloads.
- **Local Provider Option:** For strictly air-gapped or high-privacy on-premise deployments, the system provides pluggable provider abstractions (`LocalWhisperProvider`, future `LocalLLMProvider`) that keep all processing within the operator's controlled boundary.

---

## 5. Summary of Compliance Support Features

| Feature Area | Technical Mechanism | Supported Compliance Objective |
|---|---|---|
| **Access Control** | JWT verification, tenant ownership checks, UUIDv4 identifiers | Authorized access only (Principle of least privilege) |
| **Data Erasure** | Atomic cascading delete across R2 storage and PostgreSQL | Support for "Right to Erasure" / User deletion workflows |
| **Data Integrity** | Relational evidence links (`source_segment_ids`), checksums | Verifiable data lineage and auditability |
| **Storage Security** | Private R2 buckets, short-lived signed URLs (≤ 15 min expiration) | Protection against unauthorized exposure of media binaries |
| **Logging Hygiene** | Structured logs with token redaction; no plaintext PII or transcripts | Secure auditability without sensitive data retention |

