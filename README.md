# Meeting Recording Summarizer

Production-first asynchronous meeting summarization and intelligence platform with decoupled API and worker runtimes, direct-to-storage ingestion, and deterministic evidence linking.

---

## Supported Runtime Versions

* **Python:** 3.12+ (tested with Python 3.12.3)
* **Node.js:** 20+ LTS / 22+ (tested with Node.js v22.23.2)
* **npm:** 10+ (tested with npm 10.9.8)
* **Docker & Docker Compose:** Docker 24+ / Compose v2.20+

---

## Repository Structure

```text
meeting-summarizer/
├── .github/workflows/       # GitHub Actions CI workflow (ci.yml)
├── backend/                 # FastAPI REST API & Celery Worker
│   ├── app/
│   │   ├── api/v1/          # HTTP routes & health probe (/api/v1/health)
│   │   ├── core/            # Config (Pydantic BaseSettings), Celery, Logging
│   │   └── main.py          # FastAPI application factory & lifespan
│   ├── tests/
│   │   └── unit/            # Unit & configuration tests
│   ├── pyproject.toml       # Backend dependencies, ruff, mypy, pytest config
│   └── README.md
├── frontend/                # Next.js 14 App Router, TypeScript, Tailwind CSS
│   ├── src/app/             # Pages, layout, global styles
│   ├── package.json
│   ├── tsconfig.json
│   └── tailwind.config.js
├── docs/                    # Authoritative planning and architecture suite
├── Dockerfile.api           # FastAPI web server container definition
├── Dockerfile.worker        # Celery background worker container (includes FFmpeg)
├── Dockerfile.frontend      # Next.js web application container definition
├── docker-compose.yml       # Local development multi-container orchestration
├── .env.example             # Documented environment variable template
├── .gitignore
└── README.md
```

---

## Local Setup & Development

### 1. Environment Configuration

Copy the documented environment template:

```bash
cp .env.example .env
```

*Note: Default settings in `.env.example` use mock providers and local addresses. No paid cloud credentials are required to boot the application, install dependencies, or run tests.*

---

### 2. Backend Installation & Execution

```bash
cd backend

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip and install dependencies (including dev tools)
pip install --upgrade pip
pip install -e ".[dev]"

# Run quality checks
ruff check .
ruff format --check .
mypy app tests
pytest

# Start development API server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Test health check probe:
```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
{"status":"healthy","app_name":"Meeting Intelligence Summarizer","environment":"development"}
```

---

### 3. Frontend Installation & Execution

```bash
cd frontend

# Install npm dependencies
npm install

# Run quality checks
npm run typecheck
npm run lint
npm run build

# Start Next.js development server
npm run dev
```

The frontend will be accessible at [http://localhost:3000](http://localhost:3000).

---

### 4. Running with Docker Compose

To run the complete local environment (PostgreSQL 16, Redis 7, FastAPI API, Celery Worker, and Next.js):

```bash
docker compose up --build
```

---

## Quality Assurance & CI Commands

The automated CI workflow (`.github/workflows/ci.yml`) enforces the following gates:

| Component | Check | Exact Command |
|---|---|---|
| Backend | Linting | `ruff check .` |
| Backend | Formatting | `ruff format --check .` |
| Backend | Type Safety | `mypy app tests` |
| Backend | Automated Tests | `pytest` |
| Frontend | Type Safety | `npm run typecheck` |
| Frontend | Linting | `npm run lint` |
| Frontend | Production Build | `npm run build` |

