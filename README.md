# 📦 Case Workflow Engine (FastAPI + Temporal)

This project implements a **config-driven workflow engine** using:

* **FastAPI** → API layer
* **Temporal** → workflow orchestration
* **PostgreSQL** → persistence
* **SQLAlchemy** → ORM
* **JSON configs** → dynamic workflow definitions

The goal is to define workflows (multi-step forms) dynamically via configuration, rather than hardcoding logic.

---

# 🧠 Core Concept

A workflow is defined in JSON and consists of:

* Steps (e.g. location → financial → identifiers)
* Fields per step (used by UI)
* Activity per step (writes to DB)
* Next step logic

---

# 🧭 Architecture Diagram

```id="m6b8xp"
          ┌──────────────┐
          │   Frontend   │
          │ (Dynamic UI) │
          └──────┬───────┘
                 │
                 │ HTTP
                 ▼
        ┌─────────────────────┐
        │     FastAPI API     │
        │  (routers + validation)
        └──────┬──────────────┘
               │
               │ calls
               ▼
   ┌──────────────────────────┐
   │ WorkflowRuntimeService   │
   │ (starts workflows)       │
   └──────┬───────────────────┘
          │
          │ Temporal Client
          ▼
   ┌──────────────────────────┐
   │      Temporal Server     │
   │  (orchestration engine)  │
   └──────┬───────────────────┘
          │
          │ executes
          ▼
   ┌──────────────────────────┐
   │   Temporal Worker        │
   │ (workflows + activities) │
   └──────┬───────────────────┘
          │
          │ DB writes
          ▼
   ┌──────────────────────────┐
   │      PostgreSQL DB       │
   │ (case_data + workflow)   │
   └──────────────────────────┘
```

---

# 🔄 Workflow Execution Flow

```id="d2u3qv"
1. POST /cases/start
   → loads JSON config
   → starts Temporal workflow

2. GET /cases/{case_id}/state
   → returns current step + fields

3. POST /cases/{case_id}/submit
   → API validates input
   → sends signal to workflow
   → workflow runs activity
   → data saved in DB
   → workflow moves to next step
```

---

# 📁 Project Structure

## `app/core/`

### `settings.py`

* Loads environment variables using `pydantic-settings`
* Defines:

  * database connection
  * Temporal address
  * schema names

### `db.py`

* SQLAlchemy setup
* Creates:

  * engine
  * session
  * `get_db()` dependency for FastAPI

---

## `app/models/`

### `case_data.py`

* SQLAlchemy models for business data:

  * `CaseLocation`
  * `CaseFinancial`
  * `CaseRegistration`
  * `Operator`
* These are populated during workflow execution

### `workflow.py`

* (Optional / future)
* Can store workflow metadata:

  * case lifecycle
  * status tracking
  * audit logs

---

## `app/schemas/`

### `workflow_runtime.py`

* Defines the object passed into Temporal:

```python
WorkflowRuntimeInput
```

Contains:

* `case_id`
* `workflow_code`
* full workflow JSON config

---

## `app/services/`

### `workflow_config_service.py`

* Loads workflow definitions from:

```id="r8uxy6"
app/workflow_configs/workflows.json
```

* Provides:

  * `get_workflow(workflow_code)`

---

### `workflow_runtime_service.py`

* Starts Temporal workflows
* Bridges API → Temporal

Handles:

* loading config
* creating workflow input
* starting workflow execution

---

## `app/workflow_configs/`

### `workflows.json`

* Central definition of all workflows

Example:

```json id="n9wnbt"
{
  "workflows": {
    "private_lending_v1": {
      "start_step": "location",
      "steps": {
        "location": {
          "activity": "save_location_step",
          "next": "financial",
          "fields": [...]
        }
      }
    }
  }
}
```

Drives:

* UI rendering
* validation
* workflow progression

---

## `app/workflows/`

### `case_workflow.py`

* Temporal workflow definition

Responsibilities:

* holds workflow state
* tracks current step
* processes step submissions
* moves to next step

Key methods:

* `run()` → initialize workflow
* `get_state()` → return UI schema
* `submit_step()` → process step

---

### `activities.py`

* Contains business logic for each step

Each activity:

* receives `{ case_id, data }`
* writes to database

Examples:

* `save_location_step`
* `save_financial_step`
* `save_identifiers_step`

---

## `app/workers/`

### `temporal_worker.py`

* Runs Temporal worker

Registers:

* workflows
* activities

Executes:

* workflow logic
* DB operations

---

## `app/routers/`

### `case_workflow.py`

* Main workflow API

Endpoints:

#### `POST /cases/start`

* Starts a workflow instance

#### `GET /cases/{case_id}/state`

* Returns:

  * current step
  * fields
  * validation errors

#### `POST /cases/{case_id}/submit`

* Validates input
* Signals workflow
* Advances step

---

## `app/main.py`

* FastAPI entrypoint
* Registers routers
* Initializes DB

---

# ✅ Validation Strategy

### API Layer (FastAPI)

* required fields
* type validation
* returns HTTP 422

### Workflow Layer (Temporal)

* safety validation
* ensures workflow integrity

---

# 🚀 Running the Project

```bash id="0o0d0g"
docker compose up --build
```

Services:

* `physical-api` → FastAPI
* `physical-worker` → Temporal worker
* `temporal` → Temporal server
* `temporal-ui` → http://localhost:8080
* `physical-db` → PostgreSQL

---

# 🧠 Key Design Principles

* **Config-driven** → workflows defined in JSON
* **Separation of concerns**

  * API = validation + routing
  * Temporal = orchestration
  * Activities = persistence
* **Extensible** → add new workflows without code changes
* **UI-agnostic** → frontend generated from backend config

---

# 📌 Future Improvements

* Field-level validation (min/max, enums)
* File upload steps
* Persist workflow state in DB
* Role-based workflows
* Multi-user collaboration
* UI auto-generation

---

# 🧠 Summary

This system is a **dynamic workflow engine** where:

* workflows are defined in JSON
* Temporal controls execution
* FastAPI validates inputs
* activities persist data

This allows flexible, scalable workflow design without hardcoding flows.

---


# Example for implementing new workflow

process for updating workflows

update config
update models
update schemas
update seeding for lookups 
update routers lookups