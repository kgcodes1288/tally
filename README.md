# Tally

**Ask a question about your data in plain English. An AI agent does the work in an isolated sandbox, using only the data your role is allowed to see, and you can watch and steer it while it works.**

Tally is a self-hosted platform for agentic data work: reconciliations, investigations, data-quality checks and reports, delivered as CSV files, PDF reports or interactive HTML dashboards. It is a personal, open-source project built on public data.

> Status: Phases 1 to 4 are complete: data, roles and knowledge base; sandboxed agent runs with a model proxy, steering and stop; skills for reconciliations, data-quality reports, dashboards and PDF reports; and a web app with a live activity timeline. Next: hardening and the public demo. See [the architecture](docs/ARCHITECTURE.md).

## What makes it different

- **Security enforced by the database, not by a prompt.** Every task gets a short-lived database login scoped to one role. Row-level security means an agent acting for the NASA budget analyst cannot read Education's data, even with a hand-written query. This is covered by tests.
- **Isolated execution.** Each task runs in its own throwaway gVisor sandbox: no internet, no route to the host, read-only system disk, no Linux capabilities, unprivileged user. The model API key never enters the sandbox; a proxy adds it and enforces per-task and daily budgets. Attack tests prove each of these.
- **Steerable while running.** Add instructions mid-task, stop and redirect, or approve sensitive steps.
- **Grounded in business knowledge, with citations.** Each workspace has a knowledge base built from official PDFs, web pages, wiki articles, playbooks and uploaded documents. Every passage carries a citation (down to the PDF page) and an authority level, so answers can show their sources.

- **Skills with tested scripts.** The agent loads procedures on demand (reconcile two sources, data-quality check, HTML dashboard, PDF report). Each skill ships a script with its own tests, so results are consistent and the agent spends its effort on analysis, not on re-writing plumbing. Dashboards and reports use a colour-blind-safe palette and work offline.

## Workspaces

| Workspace | Data | Roles |
|---|---|---|
| Federal Spending | USAspending.gov Files A, B and C for six agencies, FY2025 (3.1M award rows) | One analyst per agency, plus an oversight lead |
| Online Retail | Olist Brazilian e-commerce, about 100K orders in nine tables | Regional managers by state, plus head of finance |
| City Operations | NYC 311 service requests, Q1 2025 (885K requests) | Borough operations managers, plus a citywide director |

## The web app

Pick a workspace and the role you are acting as, then ask in plain English. Every step the agent takes appears live: queries with their results, knowledge-base searches with citations, skills it uses, files it writes. Type a note while it works and it picks it up at its next step; press Stop to interrupt. Dashboards, PDFs and CSVs open inside the app. Agent-made pages are untrusted, so they run in a sandboxed frame (and with a `Content-Security-Policy: sandbox` header if opened directly) with no access to the app or its API.

Built with React, Vite, TypeScript and Tailwind; served by the same FastAPI service as the API.

## Run it locally

```bash
cp .env.example .env                      # then set a strong POSTGRES_PASSWORD and matching TALLY_DB_URL
docker compose --env-file .env up -d      # PostgreSQL 17 + pgvector, bound to localhost only
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
python3 data/fetch_usaspending.py 2025 72:nasa 80:education 78:energy 61:epa 46:nsf 66:sba
# Olist: download from Kaggle into data/raw/olist; NYC 311: see data/loaders/load_city.py
.venv/bin/python data/loaders/load_federal.py
.venv/bin/python data/loaders/load_retail.py
.venv/bin/python data/loaders/load_city.py
.venv/bin/python kb/ingest.py
docker build -f sandbox/Dockerfile -t tally-sandbox:dev .
(cd web && npm install && npm run build)
cd api && ../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8300   # then open http://127.0.0.1:8300
cd tests && ../.venv/bin/python -m pytest -q
```

## Data

All data is public. See [DATA_SOURCES.md](DATA_SOURCES.md) for sources and licenses.
