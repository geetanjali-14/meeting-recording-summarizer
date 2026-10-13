# COST_CONTROL.md — Cost & Token Optimization Architecture

> **Project:** Meeting Recording Summarizer  
> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Classification:** Architectural Requirement  
> **Document Owner:** Architecture Team  

---

## Table of Contents

1. [Architectural Cost Philosophy](#1-architectural-cost-philosophy)
2. [The 12 Mandatory Cost Control Principles](#2-the-12-mandatory-cost-control-principles)
3. [Token Optimization & Transcript Formatting](#3-token-optimization--transcript-formatting)
4. [Large Transcript Hierarchical Processing Strategy](#4-large-transcript-hierarchical-processing-strategy)
5. [Model Routing & Provider Strategy](#5-model-routing--provider-strategy)
6. [Cost Tracking, Pricing Versioning & Audit Metadata](#6-cost-tracking-pricing-versioning--audit-metadata)
7. [Time-Sensitive Unit Cost Projections](#7-time-sensitive-unit-cost-projections)

---

## 1. Architectural Cost Philosophy

Cost efficiency is treated as a first-class architectural concern from day one. We achieve sustainable economics through **minimal token formatting, single-pass structured reasoning where context permits, bounded hierarchical synthesis on overflow, and caching of reusable artifacts in PostgreSQL**.

---

## 2. The 12 Mandatory Cost Control Principles

1. **Never Resend Unnecessary Transcript Content:** Format input payloads compactly (strip whitespace and metadata boilerplate) before submitting to LLMs.
2. **Prefer One Structured Call When Context Fits:** When the transcript fits within the model context window, execute a single structured generation call returning all intelligence fields.
3. **Use Bounded Hierarchical Processing Only When Required:** When transcripts exceed context limits, partition into bounded chunks, extract compact intermediate facts, and perform a single synthesis call.
4. **Deterministic Code for Deterministic Tasks:** Calculate audio durations via metadata, inspect MIME types via magic bytes, compute evidence timestamps, and validate schemas using deterministic Python code.
5. **Cache Reusable Results in PostgreSQL:** Relational transcript segments and structured meeting intelligence are persisted in PostgreSQL.
6. **Do Not Re-Transcribe Unchanged Recordings:** If re-analysis or prompt refinement is requested, reuse the stored `transcript_segments` without invoking the speech-to-text API again.
7. **Retry Only Retryable Errors:** Limit retries to transient network errors (HTTP 429, 503); never retry 400 validation errors, auth failures, or context overflow errors.
8. **Intelligent Model Routing & Targeted Verification:** Default to high-throughput Groq GPT-OSS 120B as quality candidate, and Groq GPT-OSS 20B as lower-cost candidate. Completely avoid blanket secondary critic calls that would double inference costs; invoke targeted verification selectively only on flagged ambiguous or high-impact claims.
9. **Store Structured Analysis Relational Entities:** Store topics, decisions, action items, risks, and questions in relational tables so downstream UI and future Q&A do not require re-querying the LLM.
10. **Track Token Usage and Estimated Cost:** Persist `prompt_tokens`, `completion_tokens`, and `total_tokens` for every analysis execution.
11. **Record Provider-Reported Usage Separately:** Maintain raw token counts separate from calculated financial estimates.
12. **Store Pricing/Version Metadata:** Store `pricing_version` with each analysis record so historical cost estimates remain immutable when vendor pricing updates.

---

## 3. Token Optimization & Transcript Formatting

Raw transcript JSON objects carry substantial syntax overhead (brackets, quotes, nested keys). Before submission to the LLM, `TranscriptSegment` records are converted to a compact, delimited string:

```text
[SEG-01][0s-15s] SPEAKER_00 (Alice): We decided to deploy PostgreSQL from day one.
[SEG-02][16s-35s] SPEAKER_01 (Bob): I will create the Alembic migration by Friday.
```

- Reduces prompt token footprint by ~40% compared to raw JSON dumps.
- Preserves explicit `SEG-XX` identifiers for evidence citations and speaker identities.

---

## 4. Large Transcript Hierarchical Processing Strategy

```text
Transcript Size Evaluation
        │
        ├── Transcript <= Context Limit (e.g. < 40k tokens)
        │     └── Single Structured LLM Call (MeetingAnalysisAgent)
        │
        └── Transcript > Context Limit
              └── Bounded Hierarchical Chunking:
                    1. Partition transcript into 15k-token chunks (with 500-token overlap)
                    2. Chunk pass: extract compact factual bullet points + segment IDs
                    3. Synthesis pass: merge compact intermediate facts into final MeetingAnalysis schema
```

---

## 5. Model Routing & Provider Strategy

| Role | Provider / Model | Purpose / Rationale |
|---|---|---|
| **Quality LLM Candidate** | Groq (`gpt-oss-120b`) | Primary production candidate for complex reasoning, nuanced debates, and structured schema fidelity |
| **Cost LLM Candidate** | Groq (`gpt-oss-20b`) | High-throughput, lower-cost candidate for concise, standard meetings |
| **Targeted Verification** | Groq (`gpt-oss-120b`) | Selectively validates flagged ambiguous or high-impact claims (bypassed for routine valid claims) |
| **Speech-to-Text Candidate** | Groq (`whisper-large-v3-turbo`) | Timestamped audio transcription evaluated against Whisper Large V3 and a cloud alternative |
| **Speaker Diarization** | pyannote Community-1 | Local/worker turn detection and speaker clustering aligned to transcript segments |
| **Development / Mock** | MockProvider | Zero-cost deterministic offline testing |

---

## 6. Cost Tracking, Pricing Versioning & Audit Metadata

Every completed `MeetingAnalysis` record persists cost tracking metadata:

```sql
ALTER TABLE meeting_analyses ADD COLUMN prompt_tokens INTEGER;
ALTER TABLE meeting_analyses ADD COLUMN completion_tokens INTEGER;
ALTER TABLE meeting_analyses ADD COLUMN total_tokens INTEGER;
ALTER TABLE meeting_analyses ADD COLUMN estimated_cost_usd DECIMAL(10,6);
ALTER TABLE meeting_analyses ADD COLUMN pricing_version TEXT; -- e.g. "2026-10-v1"
ALTER TABLE meeting_analyses ADD COLUMN verification_performed BOOLEAN DEFAULT FALSE;
ALTER TABLE meeting_analyses ADD COLUMN verification_model TEXT;
```

---

## 7. Time-Sensitive Unit Cost Projections

> [!NOTE]
> All unit cost projections are based on October 2026 provider published rates (verified 2026-10-13) and are subject to market adjustments. Pricing is not hard-coded into architectural logic; calculations use the dynamic `pricing_version` schema.

| Pipeline Component | Initial Provider Choice | Estimated Cost per 1-Hour Meeting | Notes |
|---|---|---|---|
| **Speech-to-Text** | Groq Whisper Large V3 Turbo | ~$0.024 USD | Based on published per-minute hosted rates |
| **Speaker Diarization** | pyannote Community-1 | ~$0.003 USD | Compute amortized on worker container |
| **LLM Analysis** | Groq GPT-OSS 120B | ~$0.008 USD | ~6,000 prompt tokens + 900 completion tokens |
| **Targeted Verification** | Groq GPT-OSS 120B (Selective) | ~$0.001 USD | Amortized across ~15% of meetings requiring verification |
| **Object Storage** | Cloudflare R2 | ~$0.001 USD | 100 MB binary; zero egress fees |
| **Database & Compute** | Supabase & Containers | ~$0.006 USD | Amortized PostgreSQL and Redis platform cost |
| **Total Estimated Variable Cost** | | **~$0.043 USD** | Well below $0.10 target cap |
