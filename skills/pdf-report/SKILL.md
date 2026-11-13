---
name: pdf-report
description: Produce a professional PDF report (cover, executive summary, sections with charts and tables, cited sources, page numbers). Use when the person asks for a report, a PDF, a memo, a write-up to share, or something printable.
---

# PDF report

Write the content as a JSON spec; a tested script renders it with Tally's design (cover page, boxed summary, charts in the validated palette, tables, numbered sources, page numbers). Do not write HTML or call WeasyPrint yourself.

## 1. Plan the story
A report answers one question. Draft, in order:
- **Summary**: 3 to 5 bullet findings, each with a number, unit and period. This is what most readers will read.
- **Sections**: one per sub-question, each with short Markdown prose (2 to 6 sentences) and, where it helps, one chart and/or one table.
- **Sources**: every knowledge-base citation you relied on, exactly as `search_knowledge` returned it.

## 2. Prepare data files
Save each chart's and table's data as a small CSV in `/workspace/data`, already aggregated and sorted. Units: `"$"`, `"%"`, `"hrs"`, `"count"`.

## 3. Write the spec and render
```bash
cat > /workspace/data/report_spec.json <<'JSON'
{
  "title": "Specific title that states the subject",
  "subtitle": "Scope and period",
  "prepared_for": "<persona title>",
  "as_of": "Data source and period",
  "summary": ["**$52.7M** of NASA FY2025 File C obligations are unlinked (0.23%)."],
  "sections": [
    {"heading": "Where the gap sits",
     "body": "Markdown paragraph. **Bold** key numbers. Tables in Markdown are fine for small lists.",
     "chart": {"type": "bar", "data": "/workspace/data/by_account.csv", "x": "account", "y": "amount", "unit": "$",
               "title": "Unlinked obligations by account, US dollars", "highlight": "080-0122"},
     "table": {"data": "/workspace/data/top10.csv", "max_rows": 10, "caption": "Ten largest unlinked records."}}
  ],
  "sources": ["Tally playbook \"Federal spending reconciliation playbook\", section \"Check 3: unlinked awards\""]
}
JSON
python /workspace/.claude/skills/pdf-report/scripts/report.py /workspace/data/report_spec.json --out /workspace/out/<name>.pdf
```
Chart types: `bar`, `hbar`, `grouped_bar` (y as a list), `line` (use `series` for several lines). Long category names switch to horizontal bars automatically.

## 4. Check before you finish
Every number in the summary appears in a section; every claim from the knowledge base is in Sources; no section is a wall of text. Mention the file in your final answer.
