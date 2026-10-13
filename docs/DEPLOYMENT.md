# Production Deployment Architecture

> **Project:** Meeting Recording Summarizer  
> **Status:** Phase 0 Baseline — Frozen  
> **Last Updated:** 2026-10-09  
> **Document Owner:** Architecture & DevOps Team  

---

## 1. Production Topology & Decoupled Runtimes

The application is architected from Day One for production cloud deployment with **distinct, independently scalable runtime roles** for the HTTP API and the Background Processing Worker.

```text
                                  CLIENT / BROWSER
                                         │
                                         ▼ HTTPS
                          ┌──────────────────────────────┐
                          │ Next.js Frontend             │
                          │ (Vercel / Node Container)    │
                          │ - Next.js 14 + TS + Tailwind │
                          └──────────────┬───────────────┘
                                         │
                                         ▼ HTTPS API Calls (/api/v1/*)
                          ┌──────────────────────────────┐
                          │ Web / API Gateway Instance   │
                          │ (FastAPI on Fly.io / Render) │
                          │ - Stateless HTTP Cluster     │
                          │ - Pre-signed URL generation  │
                          └──────┬──────────────┬────────┘
                                 │              │
                    Direct Upload│              │ Dispatch Task
                    Presigned PUT│              │
                                 ▼              ▼
                 ┌──────────────────┐    ┌──────────────────────────────┐
                 │ Cloudflare R2    │    │ Redis Task Broker            │
                 │ Private Storage  │    │ (Upstash / Managed Redis 7)  │
                 │ - Zero Egress    │    │ - Celery Task Queue          │
                 └─────────┬────────┘    └──────────────┬───────────────┘
                           │                            │
                           │ Download                   │ Consumes Task
                           └───────────────────►        ▼
                                         ┌──────────────────────────────┐
                                         │ Dedicated Celery Worker      │
                                         │ Container (Fly.io / Render)  │
                                         │ - FFmpeg audio extraction    │
                                         │ - pyannote Community-1       │
                                         │ - acks_late=True reliability │
                                         └──────┬──────────────┬────────┘
                                                │              │
                                                ▼              ▼
                                     ┌─────────────┐    ┌─────────────┐
                                     │Transcription│    │ LLM Analysis│
                                     │ Provider    │    │ Provider    │
                                     │ (Groq Turbo │    │ (Groq       │
                                     │  Whisper)   │    │  GPT-OSS)   │
                                     └─────────────┘    └─────────────┘
                                                ▲
                                                │ Authoritative State, Leases,
                                                │ Attempts & Results Store
                                     ┌──────────┴──────────┐
                                     │ Managed PostgreSQL  │
                                     │ (Supabase / RDS)    │
                                     │ - Durable Data      │
                                     │ - Authoritative Job │
                                     └─────────────────────┘
```

---

## 2. Environment Configuration Contract (`.env.example`)

All configuration is loaded through Pydantic `Settings` in `app/core/config.py`.

```bash
# ==============================================================================
# 1. CORE APPLICATION SETTINGS
# ==============================================================================
APP_NAME="Meeting Intelligence Summarizer"
APP_ENV="production"                # development | staging | production
DEBUG=false
PORT=8000
HOST="0.0.0.0"
LOG_LEVEL="INFO"                    # DEBUG | INFO | WARNING | ERROR

# ==============================================================================
# 2. DATABASE CONFIGURATION (POSTGRESQL - MANDATORY FROM DAY ONE)
# ==============================================================================
DATABASE_URL="postgresql+psycopg://postgres.project_ref:[PASSWORD]@aws-0-region.pooler.supabase.com:6543/postgres?sslmode=require"
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20
DATABASE_POOL_TIMEOUT_SECONDS=30
DATABASE_POOL_RECYCLE_SECONDS=1800

# ==============================================================================
# 3. AUTHENTICATION (SUPABASE AUTH / JWT VERIFICATION)
# ==============================================================================
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
JWT_ISSUER="https://your-project.supabase.co/auth/v1"
JWT_AUDIENCE="authenticated"
JWT_ALGORITHMS=["RS256", "HS256"]
JWT_SIGNING_KEY_OR_JWKS="https://your-project.supabase.co/auth/v1/.well-known/jwks.json"

# ==============================================================================
# 4. OBJECT STORAGE (CLOUDFLARE R2 / S3 COMPATIBLE)
# ==============================================================================
STORAGE_PROVIDER="r2"               # r2 | s3
STORAGE_ACCESS_KEY_ID="r2-access-key-id"
STORAGE_SECRET_ACCESS_KEY="r2-secret-access-key"
STORAGE_BUCKET_NAME="meeting-recordings-production"
STORAGE_ENDPOINT_URL="https://your-account-id.r2.cloudflarestorage.com"
STORAGE_REGION="auto"
STORAGE_PRESIGNED_UPLOAD_EXPIRY_SECONDS=900    # 15 minutes
STORAGE_PRESIGNED_DOWNLOAD_EXPIRY_SECONDS=3600 # 1 hour

# ==============================================================================
# 5. LLM PROVIDER CONFIGURATION
# ==============================================================================
LLM_PROVIDER="groq"                 # groq | openai | mock
LLM_API_KEY="gsk_your_groq_api_key"
LLM_MODEL="gpt-oss-120b"            # primary quality candidate
LLM_LOW_COST_MODEL="gpt-oss-20b"    # lower-cost candidate
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=4096
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

# ==============================================================================
# 6. TRANSCRIPTION & DIARIZATION PROVIDERS
# ==============================================================================
TRANSCRIPTION_PROVIDER="groq_whisper_turbo" # groq_whisper_turbo | faster_whisper | mock
TRANSCRIPTION_API_KEY="gsk_your_groq_api_key"
TRANSCRIPTION_MODEL="whisper-large-v3-turbo"
TRANSCRIPTION_TIMEOUT_SECONDS=300
DIARIZATION_PROVIDER="pyannote_community_1" # pyannote_community_1 | mock
HF_TOKEN="hf_your_huggingface_token"        # for pyannote community model weights

# ==============================================================================
# 7. CELERY & REDIS BROKER CONFIGURATION
# ==============================================================================
REDIS_URL="redis://default:[PASSWORD]@aws-0-region.pooler.redislabs.com:6379/0"
CELERY_BROKER_URL="redis://default:[PASSWORD]@aws-0-region.pooler.redislabs.com:6379/0"
CELERY_RESULT_BACKEND="rpc://"              # Task status; durable results in PostgreSQL
CELERY_TASK_ACKS_LATE=true
CELERY_TASK_REJECT_ON_WORKER_LOST=true
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_WORKER_CONCURRENCY=2
WORKER_LEASE_DURATION_SECONDS=120
WORKER_HEARTBEAT_INTERVAL_SECONDS=30
WORKER_MAX_ATTEMPTS=3

# ==============================================================================
# 8. FRONTEND ENVIRONMENT CONFIGURATION (Next.js)
# ==============================================================================
NEXT_PUBLIC_API_URL="https://api.meetingsummarizer.app/api/v1"
```

---

## 3. Container Runtime Commands

The codebase supports distinct runtime entry points:

### 3.1 API Server Container (`Dockerfile.api`)
```bash
# Starts the stateless HTTP REST API server on port 8000
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
```

### 3.2 Celery Background Worker Container (`Dockerfile.worker`)
```bash
# Starts the dedicated Celery worker with late acks and fair scheduling
# Note: Container base image includes FFmpeg (apt-get install -y ffmpeg)
celery -A app.core.celery_app worker --loglevel=INFO --concurrency=2 --prefetch-multiplier=1 -O fair
```

### 3.3 Next.js Frontend Container (`Dockerfile.frontend` or Vercel)
```bash
# Production Next.js server
npm run build && npm run start -- -p 3000
```

---

## 4. Production Deployment Checklist

1. **Database:** Supabase / PostgreSQL instance provisioned with Alembic migrations applied via `alembic upgrade head`.
2. **Task Broker:** Redis instance provisioned with SSL enabled and connection strings injected into API and worker environments.
3. **Storage:** Cloudflare R2 bucket created with private ACLs and CORS enabled for frontend direct `PUT` uploads.
4. **Worker Image:** Celery worker container image built with system `ffmpeg` binary and Python dependencies.
5. **Backend API:** FastAPI container running on Fly.io / Render with HTTPS enabled.
6. **Frontend:** Next.js application deployed to Vercel or Node container with `NEXT_PUBLIC_API_URL` pointing to backend.
7. **Autoscaling:** Celery worker containers scaled horizontally based on Redis queue depth (`celery inspect active_queues`).
