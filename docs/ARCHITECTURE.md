# Tally architecture

Tally is a self-hosted platform for **agentic data work**. A person picks a workspace, asks a question or assigns a task in plain English, and an AI agent does the work inside an isolated sandbox: it reads the workspace's knowledge base, queries only the data that person's role may see, computes and reconciles, and returns a CSV, a PDF or an interactive HTML dashboard. While it works, the person can watch every step and steer it.

It is a personal, open-source, non-commercial project built entirely on public data.

## Design goals

1. **Isolation by default.** Every task runs in its own short-lived sandbox with no general internet access.
2. **Least-privilege data access.** The agent receives a database login scoped to one person's role, enforced by the database itself, not by a prompt.
3. **Secrets never enter the sandbox.** The model API key lives on the host, behind a proxy.
4. **Humans stay in the loop.** People can nudge, interrupt and approve while a task runs.
5. **Everything is observable.** Every event is recorded, which gives live progress, cost tracking and replays from one source.
6. **Built like a product.** Workspaces, roles, budgets and bring-your-own-data are first-class, even though Tally is not sold.

## Components

| Component | Technology | Role |
|---|---|---|
| Web app | React, Vite, TypeScript, Tailwind, shadcn/ui | Workspace and persona picker, task composer, live activity timeline, steering box, artifact gallery, cost meter |
| Platform API | Python 3.12, FastAPI, server-sent events | Auth, workspaces, task lifecycle, event stream, artifact serving, budgets |
| Engine | Claude Agent SDK (Python) behind an `Engine` interface | Runs the agent loop. The interface allows a second engine (for example LangGraph) to be added and compared |
| Sandbox | Docker with the gVisor runtime, one container per task | CPU, memory, time and disk limits; no network except the model proxy and the data tool |
| Model proxy | Small Python service | Adds the API key on the way out, enforces per-task and daily budgets, records token usage and cost |
| Data tool | MCP server (read-only SQL) | Connects with a short-lived, role-scoped database login; statement timeouts and row limits |
| Database | PostgreSQL 17 with pgvector | Workspace data with row-level security, platform metadata, knowledge base, event log |
| Knowledge base | pgvector, Postgres full-text search, fastembed (local embeddings), pypdf, trafilatura, python-docx | PDFs, web pages, wiki articles, playbooks and uploads, split by page or heading, every passage with a citation and an authority level; hybrid search with source diversity |
| Skills | Agent Skills folders (`skills/`), baked into the sandbox image and copied into each task's `.claude/skills` | `reconcile-sources` (DuckDB matcher: matched, left only, right only, amount difference), `data-quality-check` (profiler: duplicates, date order, negatives, outliers, missing), `html-dashboard` (JSON spec to an offline Plotly dashboard), `pdf-report` (JSON spec to a WeasyPrint PDF with matplotlib charts). Only these four are allowed; bundled skills are not |
| Analytics in the sandbox | DuckDB, pandas, Plotly, WeasyPrint | Heavy computation and output generation |

## How a task flows

1. A person submits a task in a workspace, acting as one of its roles.
2. The platform creates a task record and a **temporary database login** that inherits only that role's permissions and expires within the hour.
3. The platform starts a sandbox container for the task and runs the engine inside it. The engine reaches the model only through the proxy, and the database only through the data tool.
4. Every agent event (thinking summaries, tool calls, query results, files written, costs) is appended to the event log and streamed to the browser.
5. Messages the person types while the task runs are queued and attached to the next tool result the agent receives. A Stop button interrupts. Selected actions pause for an approve, edit or deny decision.
6. Files the agent writes to its output folder become artifacts in the gallery.
7. When the task ends, the sandbox is destroyed and the temporary login is dropped.

## Data access model

Each workspace lives in its own Postgres schema. Tables carry a **scope column** (agency, state or borough) and row-level security policies compare it with the scopes granted to the current database role.

- A **persona role** (for example "NASA budget analyst") is a Postgres role mapped to a set of scope values in `tally.role_scopes`.
- For each task, the platform creates a login role that is a member of the persona role, with a random password and a `VALID UNTIL` time.
- The data tool connects with that login. Even a crafted query cannot read rows outside the persona's scope, because the database refuses them.

## Workspaces (initial)

| Workspace | Data | Scope column | Typical tasks |
|---|---|---|---|
| Federal Spending | USAspending.gov account data for six agencies, FY2025 | agency | Reconcile account balances with award-level data, investigate unlinked awards |
| Online Retail | Olist Brazilian e-commerce (Kaggle), about 100K orders in 9 tables | state | Payment versus order-total checks, delivery performance, review analysis |
| City Operations | NYC 311 service requests, Q1 2025 | borough | Response-time analysis, backlog trends, data-quality checks |

Workspaces for public-company financials (SEC EDGAR) and immigration statistics will be added when their data is in place.

## Build phases

1. Data, roles and knowledge base
2. Agent core: sandbox, data tool, proxy, live event stream
3. Skills and outputs
4. Web app polish
5. Hardening: budgets, limits, optional Firecracker microVM isolation
6. Showcase: public replays, invite-only live runs, evals, demo video
