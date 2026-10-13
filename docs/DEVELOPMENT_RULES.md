# Development Rules & Engineering Standards

This document establishes the mandatory engineering standards, architectural invariants, and behavioral guidelines for all contributors and AI coding assistants working on the Meeting Recording Summarizer project.

---

## 1. Architectural Lessons Learned (Applied from Prior Projects)

To prevent known failure modes experienced in prior LLM and agentic projects (such as Legal Document QA), the following engineering principles are strictly enforced:

1. **Define Requirements Before Implementation:** Never write application logic against ambiguous or fluid specifications. Architecture must be frozen before coding begins.
2. **Never Discover Architecture While Debugging:** Do not iterate on foundational design (queue mechanisms, storage models, database schemas) in the middle of feature implementation.
3. **Single Authoritative Configuration Layer:** All configuration parameters must originate from validated Pydantic Settings. Never access `os.environ` directly in business logic.
4. **Isolate External Providers Behind Clean Interfaces:** Decouple all third-party SDKs (LLM, transcription, storage) behind standard abstract classes to allow zero-code-change vendor switching.
5. **Do Not Overbuild Abstractions:** Design minimal, focused interfaces that satisfy current requirements without speculative enterprise genericism.
6. **No Infrastructure Without Concrete Justification:** Do not introduce Kafka, RabbitMQ, pgvector, or unneeded vector databases until measurable product requirements demand them. Celery + Redis is our standard asynchronous task processing infrastructure, with PostgreSQL retaining authoritative durable state.
7. **Test Actual Behavior, Not Code Trivia:** Verify state transitions, tenant isolation, error handling, and API contracts rather than trivial call counts or internal function mocks.
8. **Define Correctness and Evidence Upfront:** Require deterministic evidence citations (`source_segment_ids`) and zero hallucination (`null` preference) from day one.
9. **Separate Deterministic Orchestration from AI Reasoning:** Workflows, state transitions, validation, and storage operations belong in deterministic code; LLMs perform bounded extraction only.
10. **Treat Performance Claims as Targets Until Benchmarked:** Do not bake unverified SLAs into hard architectural contracts without empirical load testing.
11. **Freeze Architecture Before Feature Phases:** Maintain disciplined phase progression without introducing forward-phase functionality prematurely.
12. **Maintain Strict Traceability:** Every feature, config flag, and test case must map back to an explicit requirement in `TRACEABILITY.md`.

---

## 2. The Core Engineering Invariants

### Rule 1: Use the simplest reliable implementation
- **Rationale:** Complexity breeds bugs, operational overhead, and maintenance friction.
- **Good:** Celery worker processes consuming tasks from Redis with `acks_late=True` and `reject_on_worker_lost=True`, coordinating with PostgreSQL as the durable source of truth.
- **Bad:** Introducing complex streaming platforms (Kafka) or custom in-process worker threads that lack multi-process resilience.

### Rule 2: No infrastructure without a concrete requirement
- **Rationale:** Premature infrastructure choices increase cost and deployment friction.
- **Good:** Redis serves strictly as the Celery task broker; PostgreSQL stores authoritative meeting records, job attempts, and results.
- **Bad:** Adding Kafka, or using Redis as the sole unbacked source of truth for job lifecycle state.

### Rule 3: No framework or library merely because it is popular
- **Rationale:** Every dependency brings security vulnerabilities, version conflicts, and cognitive load.
- **Good:** FastAPI selected specifically for native async IO and Pydantic v2 performance.
- **Bad:** Adding LangChain, LlamaIndex, or AutoGen when a bounded Pydantic agent function performs the task faster and deterministically.

### Rule 4: Keep routes thin
- **Rationale:** API route handlers should only handle HTTP protocol concerns (headers, status codes, parameter parsing, auth extraction).
- **Good:** `router.post("/meetings")` validates input via Pydantic, calls `meeting_service.create_meeting()`, and returns the response.
- **Bad:** Writing SQL queries, business validation, and storage calls directly inside the route function.

### Rule 5: Keep business logic in services and domain layers
- **Rationale:** Business logic must remain testable without mocking HTTP request/response lifecycles.
- **Good:** `MeetingService.create_meeting()` verifies user quotas, generates storage keys, and coordinates DB transactions.
- **Bad:** Scattering quota checks across route handlers and database triggers.

### Rule 6: Keep providers behind clean interfaces
- **Rationale:** Third-party AI and storage vendors change pricing, rate limits, and APIs frequently.
- **Good:** `MeetingAnalysisAgent` calls `LLMProvider.generate_structured()`, with concrete implementations `GroqProvider` and `OpenAIProvider`.
- **Bad:** Importing `from groq import Groq` inside the core analysis agent.

### Rule 7: Prefer structured outputs
- **Rationale:** Unstructured LLM text is non-deterministic and fragile to parse.
- **Good:** Enforce JSON schema validation via Pydantic models with strict typing.
- **Bad:** Asking the LLM for freeform Markdown and writing regex expressions to extract action items.

### Rule 8: Never invent meeting facts (Zero Hallucination)
- **Rationale:** Inaccurate meeting intelligence destroys user trust and creates business liability.
- **Good:** When an action item owner or due date is not explicitly stated in the transcript, set `owner = null` and `due_date = null`.
- **Bad:** Guessing that "John" owns a task because John was mentioned earlier in the meeting.

### Rule 9: Preserve evidence linkages & derive timestamps deterministically
- **Rationale:** Users must be able to audit and verify every generated summary item against the transcript.
- **Good:** Every decision, action item, and risk references `source_segment_ids: list[UUID]`; timestamps are derived deterministically by backend logic from `TranscriptSegment`.
- **Bad:** Relying on LLM-generated timestamps or generating summary bullet points with no reference to source speech.

### Rule 10: Never commit secrets or credentials
- **Rationale:** Leaked API keys lead to security breaches and financial loss.
- **Good:** All secrets injected via environment variables through Pydantic Settings; `.env` is strictly in `.gitignore`.
- **Bad:** Hardcoding default API keys or database passwords in source code.

### Rule 11: Test important behavior, not implementation trivia
- **Rationale:** Tests should give confidence during refactoring without asserting brittle internal variables.
- **Good:** Integration test asserting that User A receives HTTP 404 when querying User B's meeting ID.
- **Bad:** Unit tests asserting that an internal helper function was called exactly 3 times.

### Rule 12: Prefer free or very low-cost services where practical
- **Rationale:** Sustainable architecture maximizes margin and enables low-friction hosting.
- **Good:** Defaulting to Groq GPT-OSS 120B / 20B (sub-cent cost), Groq Whisper Large V3 Turbo, pyannote Community-1, and Cloudflare R2 (zero egress).
- **Bad:** Defaulting to expensive proprietary models (GPT-4o / Claude 3.5 Sonnet) or running redundant blanket critic LLMs on routine meetings.

### Rule 13: Minimize external API calls & handle context overflow deterministically
- **Rationale:** Network hops introduce latency, failure points, and token costs.
- **Good:** Executing a single structured LLM call when transcript fits context, and falling back to bounded hierarchical chunking and synthesis when context limits are exceeded.
- **Bad:** Making 7 sequential LLM calls to analyze 7 individual facets of a small meeting, or crashing on large meetings.

### Rule 14: Minimize LLM calls for deterministic tasks
- **Rationale:** LLMs are non-deterministic, slow, and expensive compared to CPU code.
- **Good:** Calculating audio duration using metadata, and checking MIME types using magic bytes in Python.
- **Bad:** Prompting an LLM: "What is the duration of this audio file based on timestamps?"

### Rule 15: Minimize and strictly bound retries
- **Rationale:** Unbounded retries cause thundering herds and rapid API quota exhaustion.
- **Good:** Retry only transient 429/503 errors with exponential backoff (max 2 retries).
- **Bad:** Retrying on HTTP 400 validation errors or context length overflow errors.

### Rule 16: Avoid unrelated refactoring
- **Rationale:** Scope creep introduces regression risk into unrelated features.
- **Good:** Modifying only `job_worker.py` when fixing a worker lease bug.
- **Bad:** Refactoring database models while fixing a worker bug.

### Rule 17: Justify all new dependencies
- **Rationale:** Every dependency is a supply chain liability.
- **Good:** Adding `psycopg` because async PostgreSQL binary communication is required.
- **Bad:** Adding utility packages for one-line operations available in the Python standard library.

### Rule 18: Do not implement future roadmap prematurely
- **Rationale:** Speculative code becomes technical debt before it is ever used.
- **Good:** Designing database schemas that support future Q&A without writing Q&A endpoints in MVP.
- **Bad:** Implementing vector search algorithms during Phase 1.

### Rule 19: Optimize token and compute consumption
- **Rationale:** Efficient token formatting reduces cost and speeds up processing.
- **Good:** Formatting transcript segments compactly (`[S01][12s-34s] Alice: ...`) before prompt submission.
- **Bad:** Dumping raw JSON dumps with redundant metadata into the LLM context window.

### Rule 20: Production architecture must be independent of local development
- **Rationale:** The local development machine is merely a testing environment.
- **Good:** Abstracting storage and database so code executes identically on local dev and production cloud.
- **Bad:** Designing the backend around local folder structures or local GPUs.

### Rule 21: The local machine is only a development/testing environment
- **Rationale:** Cloud deployment requirements must drive all system contracts.
- **Good:** Validating all paths and URLs against RFC specifications.
- **Bad:** Assuming `localhost:8000` or local file write permissions in application logic.

### Rule 22: Do not use local filesystem as production persistence
- **Rationale:** Ephemeral cloud containers destroy local disk on restart or scale down.
- **Good:** Storing audio/video binary objects in Cloudflare R2 / S3.
- **Bad:** Saving uploaded files to `backend/data/uploads/` in production.

### Rule 23: Do not use SQLite as production persistence
- **Rationale:** SQLite lacks multi-writer concurrency, connection pooling, and distributed scaling.
- **Good:** Using PostgreSQL from Day One.
- **Bad:** Using SQLite in production and promising to "migrate to PostgreSQL later".

### Rule 24: Do not introduce multi-agent complexity without justification
- **Rationale:** Multi-agent conversation loops create massive token overhead and debugging opacity.
- **Good:** A single well-bounded `MeetingAnalysisAgent` receiving clean transcript and emitting validated JSON, with targeted verification invoked only if flagged.
- **Bad:** Building an agent hierarchy with "Summary Agent", "Critique Agent", "Debate Agent", and "Validator Agent", or adopting LangGraph without need.

### Rule 25: Do not introduce a vector database until retrieval requirements justify it
- **Rationale:** Vector databases add operational complexity and indexing overhead.
- **Good:** Using structured single-pass analysis for meeting summarization, and evaluating PostgreSQL Full-Text Search for initial Q&A.
- **Bad:** Provisioning Qdrant / Pinecone on Day One when no vector retrieval is needed for summarization.

---

## 3. AI-Assisted Development Standards

1. **Targeted Reading:** Inspect only relevant files; do not read the entire codebase into context.
2. **Surgical Edits:** Make precise, targeted changes rather than rewriting entire files.
3. **No Speculative Abstractions:** Implement only what is required by the active phase.
4. **Follow Architecture Invariants:** Never violate the decisions recorded in `DECISIONS.md`.
5. **Pre-commit Verification:** Always run formatting, linting, and targeted tests before concluding a task.

---

## 4. Code Style & Quality Standards

- **Python:** 
  - Version: Python 3.12+
  - Formatter: Ruff / Black (88 character line limit)
  - Type Hints: 100% strict type annotations; checked with MyPy.
  - Logging: Never use `print()`; always use `app.core.logging.logger`.
- **TypeScript / Next.js:**
  - Version: Next.js 14+ App Router, TypeScript 5+, Tailwind CSS
  - Strict Mode enabled (`noImplicitAny: true`).
  - Async State: Use React Query (`@tanstack/react-query`) for server state management.
