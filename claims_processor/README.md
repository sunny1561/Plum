# Plum — Health Insurance Claims Processing System

Multi-agent AI pipeline that automates health insurance claim reviews. Accepts a claim submission (member, treatment, documents), validates documents, extracts clinical data, evaluates policy rules, detects fraud signals, and produces an explainable decision: **APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW**.

---

## AI Provider

**Anthropic Claude only** (`claude-haiku-4-5-20251001`).

Claude is used exclusively in the `DocumentExtractorAgent` for vision-based extraction from real images/PDFs. All other pipeline stages (policy evaluation, fraud detection, decision synthesis) are deterministic Python — no LLM involved.

> The `OPENAI_API_KEY` in `.env.example` is **not used** by this system. It can be ignored.

---

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.11+ | `python3 --version` |
| pip | — | `pip --version` |
| Node.js | 18+ | `node --version` |
| npm | — | `npm --version` |

---

## Setup & Run (5 minutes)

### 1 — Clone / open the project

```bash
cd /path/to/Plum   # the folder containing policy_terms.json
```

---

### 2 — Backend setup

```bash
cd claims_processor/backend

# Install Python dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
```

Open `.env` and set your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...your-key-here...
POLICY_PATH=../../policy_terms.json
PORT=8000
HOST=0.0.0.0
```

> **No API key?** The system works fully for all 12 test cases without one. The key is only needed when uploading real images/PDFs. Structured test-case data bypasses the LLM call entirely.

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

Verify it's running:

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"plum-claims-processor"}
```

Interactive API docs: **http://localhost:8000/docs**

---

### 3 — Frontend setup

Open a second terminal:

```bash
cd claims_processor/frontend

npm install
npm run dev
```

Open **http://localhost:3000** in your browser.

The UI shows all 12 test cases. Click any case to run it and see the full decision + audit trace. Click **"Run All"** to execute all 12 at once.

---

## Running the Test Suite

### Unit tests (22 tests)

```bash
cd claims_processor/backend
python -m pytest tests/ -v
```

Expected output: `22 passed`

---

### Eval runner — all 12 test cases (CLI)

```bash
cd claims_processor/backend
python -m tests.run_eval
```

Expected output:

```
✓  TC001: Wrong Document Uploaded          → VALIDATION_FAILED
✓  TC002: Unreadable Document              → VALIDATION_FAILED
✓  TC003: Documents Belong to Different Patients → VALIDATION_FAILED
✓  TC004: Clean Consultation               → APPROVED  ₹1,350
✓  TC005: Waiting Period — Diabetes        → REJECTED
✓  TC006: Dental Partial Approval          → PARTIAL   ₹8,000
✓  TC007: MRI Without Pre-Authorization    → REJECTED
✓  TC008: Per-Claim Limit Exceeded         → REJECTED
✓  TC009: Fraud Signal — Same-Day Claims   → MANUAL_REVIEW
✓  TC010: Network Hospital Discount        → APPROVED  ₹3,240
✓  TC011: Component Failure / Degradation  → APPROVED  (confidence 0.80)
✓  TC012: Excluded Treatment               → REJECTED

Summary: 12/12 passing  |  0 failing
```

---

### Via the API

```bash
# Run all 12 test cases and get a JSON report
curl -X POST http://localhost:8000/api/v1/test-cases/run-all | python3 -m json.tool

# Run a single test case
curl -X POST http://localhost:8000/api/v1/test-cases/TC004/run | python3 -m json.tool

# Submit a custom claim
curl -X POST http://localhost:8000/api/v1/claims \
  -H "Content-Type: application/json" \
  -d '{
    "member_id": "EMP001",
    "policy_id": "PLUM_GHI_2024",
    "claim_category": "CONSULTATION",
    "treatment_date": "2024-11-01",
    "claimed_amount": 1500,
    "documents": [
      {
        "file_id": "F001",
        "actual_type": "PRESCRIPTION",
        "content": {
          "doctor_name": "Dr. Arun Sharma",
          "patient_name": "Rajesh Kumar",
          "diagnosis": "Viral Fever"
        }
      },
      {
        "file_id": "F002",
        "actual_type": "HOSPITAL_BILL",
        "content": {
          "patient_name": "Rajesh Kumar",
          "total": 1500,
          "line_items": [{"description": "Consultation Fee", "amount": 1500}]
        }
      }
    ]
  }'
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/v1/claims` | Submit a claim for processing |
| `GET` | `/api/v1/claims` | List all processed claims |
| `GET` | `/api/v1/claims/{id}` | Get full result for a claim |
| `GET` | `/api/v1/test-cases` | List all 12 test cases |
| `POST` | `/api/v1/test-cases/{id}/run` | Run a specific test case |
| `POST` | `/api/v1/test-cases/run-all` | Run all 12 test cases |
| `GET` | `/api/v1/members` | List policy members |
| `GET` | `/api/v1/policy` | View loaded policy configuration |

Full interactive docs at **http://localhost:8000/docs**

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Optional* | Claude API key for real image/PDF extraction |
| `POLICY_PATH` | No (auto-detected) | Path to `policy_terms.json` |
| `PORT` | No (default 8000) | Server port |
| `HOST` | No (default 0.0.0.0) | Server host |

*All 12 test cases work without `ANTHROPIC_API_KEY`. It is only needed when uploading actual document images or PDFs.

---

## Project Structure

```
claims_processor/
│
├── backend/
│   ├── main.py                        # FastAPI app entry point
│   ├── requirements.txt               # Python dependencies
│   ├── .env.example                   # Environment variable template
│   │
│   ├── core/
│   │   ├── models.py                  # All Pydantic data models
│   │   ├── pipeline.py                # Multi-agent orchestrator
│   │   ├── policy_engine.py           # Deterministic policy rule engine
│   │   └── trace.py                   # Audit trace builder
│   │
│   ├── agents/
│   │   ├── document_validator.py      # Stage 1: blocking validation gate
│   │   ├── document_extractor.py      # Stage 2: Claude vision extraction
│   │   ├── fraud_detector.py          # Stage 3: fraud signal detection
│   │   └── decision_maker.py          # Stage 4: final decision synthesis
│   │
│   ├── api/
│   │   └── routes.py                  # FastAPI route handlers
│   │
│   └── tests/
│       ├── conftest.py                # Shared fixtures
│       ├── test_policy_engine.py      # 13 policy engine unit tests
│       ├── test_agents.py             # 9 agent unit tests
│       └── run_eval.py                # CLI eval runner for all 12 cases
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── layout.tsx             # Root layout
│       │   └── page.tsx               # Main dashboard (test case runner)
│       ├── components/
│       │   ├── DecisionCard.tsx       # Decision result display
│       │   └── TraceViewer.tsx        # Audit trace timeline
│       └── lib/
│           ├── api.ts                 # API client
│           └── types.ts               # TypeScript types
│
├── ARCHITECTURE.md                    # System design + scaling plan
├── COMPONENT_CONTRACTS.md            # Component interfaces
└── EVAL_REPORT.md                    # Full results for all 12 test cases
```

---

## Pipeline Architecture

```
ClaimSubmission
      │
      ▼
┌─────────────────────────────────────┐
│    Stage 1: DocumentValidatorAgent   │  ← No LLM. Fast. Blocking gate.
│  • Required doc type completeness    │
│  • Unreadable document detection     │
│  • Cross-doc patient identity check  │
│  STOPS HERE if any check fails       │
└──────────────────┬──────────────────┘
                   │ (passes)
      ▼
┌─────────────────────────────────────┐
│    Stage 2: DocumentExtractorAgent   │  ← Claude claude-haiku-4-5 (vision)
│  Parallel extraction per document    │    OR structured content pass-through
│  Graceful per-doc failure handling   │
└──────────────────┬──────────────────┘
                   │
      ┌────────────┴────────────┐
      ▼                         ▼
┌─────────────┐       ┌──────────────────────┐
│  Stage 3:   │       │  Stage 4:             │
│  Fraud      │       │  PolicyEngine         │  ← Pure Python. No LLM.
│  Detector   │       │  • Waiting periods    │
│             │       │  • Exclusions         │
│  Can fail   │       │  • Pre-auth checks    │
│  safely —   │       │  • Per-claim limits   │
│  pipeline   │       │  • Financial calc     │
│  continues  │       │  • Line-item rules    │
└──────┬──────┘       └──────────┬───────────┘
       └────────────┬────────────┘
                    ▼
┌─────────────────────────────────────┐
│    Stage 5: DecisionMaker            │  ← Deterministic synthesis
│  MANUAL_REVIEW > REJECTED >          │
│  PARTIAL > APPROVED                  │
│  Confidence score + full trace       │
└─────────────────────────────────────┘
```

---

## Key Design Decisions

**LLMs only for extraction, deterministic code for policy rules.**
Policy rules are code — versioned, testable, auditable. LLM-driven policy evaluation would be non-deterministic and hard to audit.

**Validation gate before extraction.**
Wrong documents are caught before any LLM call, saving cost and latency.

**Graceful degradation.**
If any agent fails (e.g. TC011: simulated fraud detector failure), the pipeline continues, marks the component as degraded, reduces the confidence score, and recommends manual review.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full design rationale and scaling plan.

---

## Deliverables Checklist

- [x] Working system with UI — `http://localhost:3000`
- [x] All 12 test cases passing — `python -m tests.run_eval`
- [x] Architecture document — `ARCHITECTURE.md`
- [x] Component contracts — `COMPONENT_CONTRACTS.md`
- [x] Eval report — `EVAL_REPORT.md`
- [x] Unit tests (22 passing) — `python -m pytest tests/ -v`
- [ ] Demo Video (8-12 minutes) — [Google Drive Demo Video (Placeholder)](https://drive.google.com/drive/folders/your-dummy-link-here)
