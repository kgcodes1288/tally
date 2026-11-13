---
name: html-dashboard
description: Build a polished, interactive, self-contained HTML dashboard (KPI tiles, charts, tables, notes, sources) that works offline. Use when the person asks for a dashboard, an interactive report, charts or a visual summary.
---

# HTML dashboard

You describe the dashboard as a JSON spec; a tested script renders it in Tally's design system (validated colour-blind-safe palette, consistent typography, hover tooltips, and a data table behind every chart). Do not hand-write HTML or chart code.

## 1. Decide what the dashboard must answer
Pick at most 3 or 4 KPI tiles (the headline numbers) and 2 to 6 charts. Each chart answers one question; its title states the question or the finding.

## 2. Choose the right chart for each question
| Question | type |
|---|---|
| Compare categories (ranking) | `bar` (sorted `desc`); long category names automatically turn horizontal |
| Compare two or three measures per category | `grouped_bar` with `y` as a list |
| Parts of a whole across categories | `stacked_bar` |
| Change over time | `line` (x = date or period). Several series: long data with `series` |
| Relationship between two measures | `scatter` (at most 3 series) |
| Exact values people will look up | a `tables` entry |
| One headline number | a KPI tile, not a chart |

Never put two measures with different units on one chart; make two charts instead. Use `highlight` to emphasise one category (for example the persona's own agency) and grey out the rest. Use `status` on a KPI only for a real judgement (`good`, `warning`, `critical`); it renders with an icon and a label.

## 3. Prepare the data
Save each chart's data as a small, already-aggregated CSV in `/workspace/data` (via `export_query` or pandas). Units: `"$"`, `"%"`, `"hrs"`, or `"count"`. Percentages are values like `12.5`, not `0.125`.

## 4. Write the spec and render
```bash
cat > /workspace/data/dashboard_spec.json <<'JSON'
{
  "title": "Short, specific title",
  "subtitle": "Scope: who, what, when",
  "as_of": "Data source and period",
  "kpis": [{"label": "Unlinked obligations", "value": 52703187.65, "unit": "$", "note": "0.23% of File C", "status": "warning"}],
  "charts": [{"title": "Unlinked obligations by account", "subtitle": "FY2025, US dollars", "type": "bar",
              "data": "/workspace/data/by_account.csv", "x": "account", "y": "amount", "unit": "$", "sort": "desc"}],
  "tables": [{"title": "Ten largest unlinked records", "data": "/workspace/data/top10.csv", "max_rows": 10}],
  "notes": ["Method, filters, exclusions and caveats, one per line"],
  "sources": ["Citations exactly as search_knowledge returned them"]
}
JSON
python /workspace/.claude/skills/html-dashboard/scripts/dashboard.py /workspace/data/dashboard_spec.json --out /workspace/out/<name>.html
```
Add `"wide": true` to a chart to give it the full width. The script refuses charts with too many series and explains how to fix them.

## 5. Check before you finish
Re-read the spec: every number has a unit and a period, titles are specific, notes state the method and exclusions, and sources are cited. Mention the file in your final answer.
