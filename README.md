# Tally

**Ask a question about your data in plain English. An AI agent does the work in an isolated sandbox, using only the data your role is allowed to see, and you can watch and steer it while it works.**

Tally is a self-hosted platform for agentic data work: reconciliations, investigations, data-quality checks and reports, delivered as CSV files, PDF reports or interactive HTML dashboards. It is a personal, open-source project built on public data.

> Status: Phases 1 and 2 are complete: data, roles and knowledge base, plus sandboxed agent runs with a model proxy, steering, stop and a streaming API. Next: skills and polished outputs. See [the architecture](docs/ARCHITECTURE.md).

## What makes it different

- **Security enforced by the database, not by a prompt.** Every task gets a short-lived database login scoped to one role. Row-level security means an agent acting for the NASA budget analyst cannot read Education's data, even with a hand-written query. This is covered by tests.
- **Isolated execution.** Each task runs in its own throwaway gVisor sandbox: no internet, no route to the host, read-only system disk, no Linux capabilities, unprivileged user. The model API key never enters the sandbox; a proxy adds it and enforces per-task and daily budgets. Attack tests prove each of these.
- **Steerable while running.** Add instructions mid-task, stop and redirect, or approve sensitive steps.
- **Grounded in business knowledge, with citations.** Each workspace has a knowledge base built from official PDFs, web pages, wiki articles, playbooks and uploaded documents. Every passage carries a citation (down to the PDF page) and an authority level, so answers can show their sources.

## Workspaces

| Workspace | Data | Roles |
|---|---|---|
| Federal Spending | USAspending.gov Files A, B and C for six agencies, FY2025 (3.1M award rows) | One analyst per agency, plus an oversight lead |
| Online Retail | Olist Brazilian e-commerce, about 100K orders in nine tables | Regional managers by state, plus head of finance |
| City Operations | NYC 311 service requests, Q1 2025 (885K requests) | Borough operations managers, plus a citywide director |

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
cd tests && ../.venv/bin/python -m pytest -q
```

## Data

All data is public. See [DATA_SOURCES.md](DATA_SOURCES.md) for sources and licenses.
