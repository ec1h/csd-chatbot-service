# CSD Chatbot

A conversational API for municipal service request intake and classification for the City of Johannesburg. The system guides users through describing an issue, assigns a call type from a structured taxonomy, collects location via a frontend popup, and confirms the report before submission.

---

## Overview

The CSD (Customer Service Delivery) Chatbot is a stateful HTTP API that:

- Accepts natural-language descriptions of municipal issues across all major service domains: water, electricity, roads, waste, transport (metro bus), fire, EMS, and more.
- Classifies intent using a two-pipeline architecture: an optimized network-based classifier (default) or a legacy keyword-and-embedding pipeline.
- Manages conversation state across turns and persists sessions in PostgreSQL.
- Collects location exclusively through a frontend map/address popup — never from message text.
- Returns a clean, minimal JSON response with no redundant fields.

All request/response payloads are JSON. Authentication is via API key (header or Bearer token). The service is built with FastAPI and runs in Docker.

---

## Architecture

**Application entry:** `app.py` — loads configuration, selects the classification pipeline, initializes the database pool, mounts routes and middleware, and exposes a Mangum handler for serverless deployment.

**Core components:**

- **API (`src/api/`)**: Route handlers (`endpoints.py`), API key verification (`dependencies.py`), middleware (CORS, request size limits, error handling), optional monitoring routes.
- **Core (`src/core/`)**: Active orchestrator (`orchestrator.py`), enhanced LLM-driven orchestrator (`enhanced_orchestrator.py`), session manager, DSPy pipeline initialization, issue normalization, domain logic, slot/clarification logic.
- **Classification (`src/classification/`)**: `SmartClassifier` with `direct_pattern_match` and TF-IDF semantic retrieval, optimized network-based classifier, embeddings, classifier service.
- **LLM (`src/llm/`)**: `ContextAnalyzer` — retrieval-augmented LLM analysis with structured JSON output, location stripping before retrieval, prompt templates (`prompts/context_analyzer.txt`). `CallTypeRetriever` — TF-IDF-based candidate retrieval.
- **Conversation (`src/conversation/`)**: State machine (`conversation_state.py`, `decision_engine.py`), `CaseMemory` (active orchestrator), `ContextMemory` (enhanced orchestrator), response generator, issue summary builder, domain/intent detection, frontend signal helpers.
- **Data (`src/database/`)**: PostgreSQL connection pool with retry logic and per-query statement timeouts.
- **Config / Security / Utils (`src/config/`, `src/security/`, `src/utils/`)**: Settings, rate limiting, input sanitization, data loaders, helpers, analytics.

**Conversation states:** `OPEN` → `ISSUE_BUILDING` → `AWAITING_CLARIFICATION` | `NEEDS_LOCATION` → `CONFIRMING` → `SUBMITTED`. The decision engine does not leave `SUBMITTED` and caps clarification turns to prevent infinite loops.

**Location rule:** Location has exactly one source — the frontend map/address popup triggered when `needs_location: true` is returned. The `ContextAnalyzer` strips location phrases (e.g. "on the road", "near the park", "at 123 Main St") from user messages before classification so they never influence call-type matching or appear in `issue_summary`. The orchestrator never extracts or stores location from message text; all `memory.location` assignments come exclusively from `body.location` (the frontend popup payload).

**Data flow:**

```
User message → API (auth, sanitize) → session load
  → process_user_message (orchestrator.py)
      → SmartClassifier (direct_pattern_match → TF-IDF → LLM fallback)
      → ContextAnalyzer (strip location → retrieve candidates → LLM → structured JSON)
      → decision engine / state transition
  → session save → clean JSON response
```

---

## Technology Stack

- **Runtime:** Python 3.10+
- **Framework:** FastAPI
- **Database:** PostgreSQL (sessions, API keys)
- **LLM:** Azure OpenAI (GPT-4.1) via DSPy
- **Embeddings:** `sentence-transformers` (`all-MiniLM-L6-v2`) for the legacy pipeline
- **Classification:** TF-IDF + cosine similarity (`CallTypeRetriever`), pattern matching (`SmartClassifier`), optional network-based optimized classifier
- **Data:** Call-type taxonomy and metadata loaded from JSON under `data/refined data/files/`
- **Deployment:** Docker Compose (local/production), Mangum (AWS Lambda/serverless)

---

## Prerequisites

- Python 3.10 or later
- PostgreSQL 12+
- Docker and Docker Compose
- Azure OpenAI access (endpoint, API key, deployment name, API version)

---

## Configuration

Copy `.env.example` to `.env` and set the following variables.

**Required:**

| Variable | Description |
|---|---|
| `POSTGRES_URI` | PostgreSQL connection string, e.g. `postgresql://user:pass@host:port/dbname` |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | Deployment name, e.g. `gpt-4.1` |
| `AZURE_OPENAI_API_VERSION` | API version, e.g. `2024-12-01-preview` |
| `AZURE_OPENAI_MODEL_NAME` | Model name (same as deployment in most cases) |

**Optional:**

| Variable | Default | Description |
|---|---|---|
| `USE_OPTIMIZED_PIPELINE` | `true` | Use the network-based classifier. Set `false` for the legacy embedding pipeline. |
| `USE_ENHANCED_ORCHESTRATOR` | `false` | Use the pure-LLM `EnhancedOrchestrator`. Default is the existing `orchestrator.py`. |
| `MAX_CLARIFICATION_TURNS` | `3` | Maximum clarification exchanges before forcing state progression. |
| `SESSION_TIMEOUT_MINUTES` | `30` | Session inactivity timeout. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `ENV` | `development` | Runtime environment (`development` / `production`). |

---

## Installation

1. Clone the repository and enter the project directory.

2. Create a virtual environment and install dependencies:

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Copy and configure the environment file:

   ```bash
   cp .env.example .env
   # edit .env with your credentials
   ```

---

## Database Setup

1. Ensure PostgreSQL is reachable at the address in `POSTGRES_URI`.

2. Run the init script to create tables and schema:

   ```bash
   psql "$POSTGRES_URI" -f init.sql
   ```

   When using Docker Compose, `init.sql` is mounted into the Postgres container and runs automatically on first start.

3. Create or update the test API key:

   ```bash
   source venv/bin/activate
   python setup_test_api_key.py
   ```

   The script prints the key value (e.g. `test-key.test-secret-123`) for use in the `X-API-Key` header.

---

## Running the Application

**Docker Compose (recommended):**

```bash
docker compose up --build
```

- PostgreSQL: container `csd_postgres`, host port `5434`, database `ec1`.
- Application: container `csd_chatbot`, host port `8001`.

After any code change, force a full rebuild:

```bash
docker compose up --force-recreate -d
```

**Local (legacy pipeline):**

```bash
./start_legacy.sh
```

**Local (optimized pipeline):**

```bash
./start_optimized.sh
```

---

## API Reference

**Base URL:** `http://localhost:8001`

**Authentication:** All endpoints except `/health` and `/` require a valid API key:

- `X-API-Key: <key_id>.<secret>`
- or `Authorization: Bearer <key_id>.<secret>`

**Endpoints:**

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness / health check |
| `GET` | `/` | Root ping |
| `POST` | `/chat` | Process a user message, returns next response |
| `POST` | `/chatStream` | Same as `/chat` with Server-Sent Events streaming |
| `POST` | `/getChatMessages` | Paginated message history for a session |
| `POST` | `/getChatHistory` | Chat history alias |
| `POST` | `/updateChatTitle` | Update the title of a chat session |

**Request body (`/chat`, `/chatStream`):**

```json
{
  "chat_id": "string (optional)",
  "session_id": "string (optional)",
  "message": "string (required, max 5000 chars)",
  "location": {
    "address": "123 Main Street",
    "latitude": -26.2041,
    "longitude": 28.0473
  }
}
```

`location` is only sent when the user has completed the frontend location popup. It is never extracted from `message` text.

**Response shape:**

```json
{
  "session_id": "12d:1772525494857:9a90e26b",
  "chat_message_id": "1772525904.321",
  "created": "2026-03-03T08:18:24.314021+00:00",
  "message": {
    "response": "Done! Your report is logged. Thanks for letting us know.",
    "needs_location": false,
    "chat_locked": true
  },
  "classification": {
    "call_type_code": "20021",
    "call_type_description": "No Supply",
    "confidence": 0.95
  },
  "state": "submitted",
  "suggested_answers": [],
  "frontend_flags": {
    "needs_location": false,
    "show_map": false,
    "conversation_done": true,
    "chat_locked": true,
    "show_confirmation": false
  },
  "chat_message_type": "Assistant",
  "awaitingConfirmation": false
}
```

**Frontend flag reference:**

| Flag | Meaning |
|---|---|
| `needs_location` | Show the location popup / map picker |
| `show_map` | Alias for `needs_location` (map visibility) |
| `conversation_done` | Chat is complete; prompt user to start new session |
| `chat_locked` | Input is locked; no further messages accepted |
| `show_confirmation` | Show a confirmation UI step |
| `awaitingConfirmation` | Top-level alias for `show_confirmation` |

`classification` is `null` until a call type has been identified. Once known it persists in every response for that session.

When `USE_OPTIMIZED_PIPELINE=true`, additional admin/monitoring routes are mounted under `/api/v1/admin/` (health, stats, taxonomy, similarity). See `src/api/monitoring_endpoints.py`.

---

## Project Structure

```
.
├── app.py                         # Application entry, pipeline selection, route mounting
├── init.sql                       # Database schema and initial data
├── setup_test_api_key.py          # Test API key creation/update (PBKDF2)
├── start_legacy.sh                # Run with legacy pipeline
├── start_optimized.sh             # Run with optimized pipeline
├── requirements.txt
├── docker-compose.yml
├── Dockerfile                     # Lambda/serverless build
├── Dockerfile.local               # Local / Docker Compose build
├── .gitignore
├── memory-bank/                   # Project state tracking
│   ├── current-state.txt          # Canonical state of all changes and golden rules
│   ├── decisions.log
│   ├── completed-steps.txt
│   └── pending-steps.txt
├── data/
│   ├── call-types-city-power.csv
│   ├── call-types-joburg-water.csv
│   ├── call_types/
│   │   ├── call_type_metadata.json        # ACTIVE taxonomy (used by classifier)
│   │   └── domain_hierarchy.json
│   └── refined data/
│       └── files/                 # Per-department JSON call-type data
│           ├── all_call_types_combined.json
│           ├── City_Power.json
│           ├── MetroBus.json
│           └── ... (one file per department)
├── scripts/                       # Maintenance scripts (run inside Docker)
│   ├── audit_vector_space.py      # Find call types too close in TF-IDF space
│   ├── rebalance_keywords.py      # Enrich keywords across all call types
│   ├── precompute_call_type_embeddings.py
│   ├── audit_keywords.py
│   └── systematic_keyword_enhancement.py
├── src/
│   ├── api/
│   │   ├── endpoints.py           # /chat, /chatStream, history, title routes
│   │   ├── dependencies.py        # API key verification
│   │   ├── middleware.py          # CORS, request size, error handling
│   │   └── monitoring_endpoints.py
│   ├── classification/
│   │   ├── smart_classifier.py    # direct_pattern_match + TF-IDF + LLM fallback
│   │   ├── classifier_service.py
│   │   ├── call_type_matcher.py
│   │   ├── call_type_network.py
│   │   ├── optimized_classifier.py
│   │   ├── hierarchical_filter.py
│   │   ├── domain_detector.py
│   │   ├── semantic_concepts.py
│   │   ├── embeddings.py
│   │   └── cache/
│   │       └── network_cache.pkl  # Generated at startup — gitignored
│   ├── conversation/
│   │   ├── conversation_state.py  # ConversationState enum
│   │   ├── decision_engine.py     # State-transition rules
│   │   ├── case_memory.py         # Session memory (active orchestrator)
│   │   ├── context_memory.py      # Session memory (enhanced orchestrator)
│   │   ├── response_generator.py
│   │   ├── issue_summary_builder.py
│   │   ├── domain_detector.py
│   │   ├── frontend_signals.py
│   │   └── intent_detector.py
│   ├── core/
│   │   ├── orchestrator.py        # Active: messages → state machine
│   │   ├── enhanced_orchestrator.py   # LLM-only path (USE_ENHANCED_ORCHESTRATOR=true)
│   │   ├── session_manager.py
│   │   ├── domain_logic.py
│   │   ├── issue_normalizer.py
│   │   ├── dspy_pipeline.py
│   │   ├── progressive_issue_builder.py
│   │   ├── clarification.py
│   │   ├── slot_clarification.py
│   │   ├── intent_extraction.py
│   │   └── circuit_breaker.py
│   ├── llm/
│   │   ├── context_analyzer.py    # Location stripping + retrieval + LLM analysis
│   │   ├── retrieval.py           # CallTypeRetriever (TF-IDF cosine similarity)
│   │   └── prompts/
│   │       └── context_analyzer.txt
│   ├── models/
│   │   └── schemas.py             # Pydantic request/response models
│   ├── database/
│   │   ├── connection.py
│   │   └── pool.py
│   ├── security/
│   │   ├── auth.py
│   │   ├── rate_limiter.py
│   │   └── input_sanitizer.py
│   ├── config/
│   │   └── settings.py
│   └── utils/
│       ├── data_loader.py
│       ├── optimized_loader.py
│       ├── helpers.py
│       ├── analytics.py
│       ├── error_handling.py
│       └── performance_monitor.py
└── tests/
    ├── test_core.py               # Health, greeting, full flow, auth, validation
    ├── test_all_classifications.py # All call-type classification coverage tests
    └── test_context_awareness.py  # Context / pronoun-resolution tests
```

---

## Classification Pipeline

**Call-type resolution order (per message):**

1. **Direct pattern match** — `smart_classifier.py` runs ~200 regex patterns mapped to validated call type codes from the taxonomy. Fastest path; no LLM required.
2. **TF-IDF retrieval** — `CallTypeRetriever` strips location phrases from the message first, then retrieves the top-10 candidate call types by cosine similarity.
3. **LLM analysis** — `ContextAnalyzer` sends the stripped message, conversation history, and retrieved candidates to GPT-4.1 via DSPy. Returns a structured JSON object with intent, issue extraction (location-free `issue_summary`), call-type candidates with confidence scores, and conversation guidance.
4. **Fallback** — if the LLM times out or returns malformed output, a deterministic fallback based on domain keyword detection responds with a clarification prompt.

**Location stripping rule:** Before retrieval and before the LLM prompt, `ContextAnalyzer.strip_location_from_issue()` removes common trailing location phrases (e.g. "on the road", "near the park", "outside the building") so classification is based purely on the issue type.

---

## Testing

Install test dependencies:

```bash
pip install pytest httpx
```

Run the full test suite:

```bash
python -m pytest tests/ -v
```

Run classification-specific tests:

```bash
python -m pytest tests/test_all_classifications.py -v
```

**Inside Docker:**

```bash
docker exec csd_chatbot python -m pytest tests/test_all_classifications.py -v
```

**Audit scripts (run inside Docker):**

```bash
# Find call types that are too close in TF-IDF space (potential misclassification)
docker exec csd_chatbot python scripts/audit_vector_space.py

# Rebalance and enrich keywords across all call types
docker exec csd_chatbot python scripts/rebalance_keywords.py

# Recompute all call-type embeddings from scratch
docker exec csd_chatbot python scripts/precompute_call_type_embeddings.py --force
```

---

## Deployment

### Docker (local / development)

```bash
docker compose up --force-recreate -d
```

The Compose file defines health checks, restart policies, and a 2 GB memory limit on the app container. PostgreSQL runs alongside it and the app waits for the DB health check to pass before starting.

### AWS TEST Environment (Terraform + ECS Fargate)

**Infrastructure:** `terraform/` directory. TEST only — AWS account `905418043725`, region `af-south-1`.

**Prerequisites:** Terraform ≥ 1.0, AWS CLI authenticated as `csd-nonprod-userfull`.

#### Phase 0 — Verify credentials
```bash
aws sts get-caller-identity --profile csd-nonprod-userfull
export AWS_PROFILE=csd-nonprod-userfull
export AWS_REGION=af-south-1
```

#### Phase 1 — Bootstrap remote state (one-time only)
```bash
cd terraform/global/s3-backend
terraform init
terraform apply -auto-approve
cd ../../..
```

#### Phase 2 — Create Azure OpenAI secret (manual, before Terraform apply)
```bash
aws secretsmanager create-secret \
  --name "test/csd-chatbot/azure-openai" \
  --description "Azure OpenAI credentials for CSD Chatbot Test" \
  --secret-string '{
    "api_key": "<your-key>",
    "endpoint": "https://ec1-azureopenai-askjo.openai.azure.com",
    "deployment": "gpt-4.1",
    "api_version": "2024-12-01-preview"
  }' \
  --tags Key=Environment,Value=test Key=Service,Value=csd-chatbot
```

#### Phase 3 — Deploy infrastructure
```bash
cd terraform/environments/test
terraform init
terraform plan
terraform apply -auto-approve
cd ../../..
```

#### Phase 4 — Build, tag, and push Docker image
```bash
ECR_URL=$(terraform -chdir=terraform/environments/test output -raw ecr_repository_url)
aws ecr get-login-password --region af-south-1 \
  | docker login --username AWS --password-stdin 905418043725.dkr.ecr.af-south-1.amazonaws.com
docker build -f Dockerfile.local -t csd-chatbot-test:latest .
docker tag csd-chatbot-test:latest ${ECR_URL}:latest
docker push ${ECR_URL}:latest
```

#### Phase 5 — Force ECS deployment
```bash
aws ecs update-service \
  --cluster csd-test-cluster \
  --service csd-chatbot-test \
  --force-new-deployment \
  --region af-south-1
aws ecs wait services-stable \
  --cluster csd-test-cluster \
  --services csd-chatbot-test
```

#### Verify
```bash
aws ecs describe-services \
  --cluster csd-test-cluster \
  --services csd-chatbot-test \
  --query 'services[0].{Status:status,Running:runningCount,Desired:desiredCount}' \
  --output table

aws rds describe-db-instances \
  --db-instance-identifier test-csd-chatbot-db \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Endpoint:Endpoint.Address}' \
  --output table
```

#### Teardown
```bash
cd terraform/environments/test && terraform destroy -auto-approve
```

**What Terraform creates (TEST):**

| Resource | Details |
|---|---|
| RDS PostgreSQL | `test-csd-chatbot-db`, db.t3.small, 20 GB gp3, encrypted |
| Secrets Manager | `test/csd-chatbot/database` (auto-generated password) |
| Secrets Manager | `test/csd-chatbot/azure-openai` (manual — must exist before apply) |
| ECR Repository | `csd-chatbot-test`, scan-on-push, 10-image lifecycle |
| CloudWatch Logs | `/ecs/csd-chatbot-test`, 30-day retention |
| ECS Task | 1 vCPU / 2 GB RAM, Fargate, secrets injected via JSON key extraction |
| ECS Service | `csd-chatbot-test`, desired=1, private subnets |

**What Terraform reuses (existing TEST infrastructure):**

| Resource | ID / Name |
|---|---|
| VPC | `vpc-0c70f9c141381565b` |
| ECS Cluster | `csd-test-cluster` |
| IAM Roles | `ecsTaskExecutionRole`, `ecsTaskRole` |

**Serverless:** The `Mangum` handler in `app.py` wraps the FastAPI app for AWS Lambda / API Gateway deployment using `Dockerfile` (Lambda base image). `Dockerfile.local` is used for ECS / Docker Compose.

---

## Error Handling

- All unhandled exceptions are caught by a global exception handler and a middleware layer. Responses are JSON with HTTP 500 and an `error_id` for log correlation.
- Database connections use a pool with retry logic and a 3-second per-query statement timeout.
- Session load failures return an in-memory fallback session so the API can respond in a degraded state rather than crashing.
- LLM timeouts (10-second cutoff) fall back to a deterministic domain-keyword response.

---

## License

Proprietary. All rights reserved.
