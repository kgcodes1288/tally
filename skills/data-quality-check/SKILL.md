---
name: data-quality-check
description: Profile a dataset and find data-quality problems (missing values, duplicates, impossible dates, negative or extreme values, broken categories) before analysis or when asked to assess, audit or validate data quality.
---

# Data-quality check

Run this before trusting a dataset for analysis, or when the person asks about data quality. Findings are a deliverable in their own right: report them, never silently drop rows.

## 1. Check the knowledge base first
Call `search_knowledge` for "data quality" plus the table name. Workspace playbooks list known issues (for example negative response times or a missing borough) and how to treat them.

## 2. Export the data
Use `export_query` to save the rows to `/workspace/data/<name>.csv`. For very large tables, export only the columns you need, or a clearly stated filter.

## 3. Run the profiler
```bash
python /workspace/.claude/skills/data-quality-check/scripts/dq_profile.py /workspace/data/<name>.csv \
  --key unique_key \
  --date-order created_date:closed_date \
  --non-negative response_hours \
  --out /workspace/out/<name>_data_quality
```
Options (all optional, repeatable where it makes sense):
- `--key col[,col]`: columns that should be unique together
- `--date-order start:end`: rows where end is before start are flagged
- `--non-negative col`: negative values are flagged
- `--required col`: missing values are flagged as errors rather than just profiled
It writes `<out>.md` (readable report) and `<out>.json` (machine-readable), and prints the findings.

## 4. Judge each finding
For every check that fails, state: how many rows, what share, an example, the likely cause, and the **impact on the question being asked** (for example "exclude the 364 negative response times from medians; they are 0.04 percent of rows"). Distinguish errors (impossible values) from warnings (unusual but possible).

## 5. Report
Start with an overall verdict (fit for purpose, fit with caveats, or not fit), then a table of findings ordered by impact, then what you excluded or adjusted and why. Link the report files.
