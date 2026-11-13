---
name: reconcile-sources
description: Reconcile two data sources that should agree (ledger vs sub-ledger, payments vs orders, File A vs File B, system vs report). Use when asked to reconcile, tie out, match, validate totals between sources, or explain why two numbers differ.
---

# Reconcile two sources

Reconciliation answers three questions: **do the totals agree, which records differ, and why.** Follow these steps in order.

## 1. Define the reconciliation before touching data
Write down, in one line each:
- **Left source** and **right source** (which is authoritative? Usually the accounting or system-of-record side. Check `search_knowledge` for a playbook that says so.)
- **Match key** (for example `treasury_account_symbol`, `order_id`). If the sources use different grain, aggregate both to a shared key first.
- **Amount column(s)** to compare, with units.
- **Tolerance**: default 0.01 for currency, or the materiality threshold in the workspace playbook.
- **Period and filters**, applied identically to both sides.

## 2. Pull both sides at the same grain
Use `export_query` to save each side as a CSV in `/workspace/data`, already aggregated to the match key with `GROUP BY`. One row per key on each side.

## 3. Run the matcher
```bash
python /workspace/.claude/skills/reconcile-sources/scripts/reconcile.py \
  --left /workspace/data/left.csv --right /workspace/data/right.csv \
  --key order_id --amount amount --tolerance 0.01 \
  --left-name "Items + freight" --right-name "Payments" \
  --out /workspace/out/reconciliation
```
Use `--key a,b` for a composite key and `--amount x,y` for several amount columns (compared pairwise by name).
It writes `<out>_exceptions.csv` (every key that is not matched, with both values and the difference),
`<out>_summary.json` and prints a summary table. Statuses:
- `matched`: within tolerance
- `left_only` / `right_only`: key present on one side only
- `amount_diff`: present on both sides, difference above tolerance

## 4. Explain the differences
For the largest exceptions and each status group, look for a cause in the data (status codes, dates near period end, payment types, installments, adjustments, deobligations) and in the knowledge base. Separate:
- **Explained** (a documented or clearly evidenced reason)
- **Likely** (strong pattern, not confirmed)
- **Unexplained** (needs a person to investigate)

## 5. Report
Lead with the answer: reconciled or not, the net and gross difference, and where it concentrates. Then a table by status and cause, the top 10 exceptions, the method (sources, key, tolerance, period), citations, and the output files. Never adjust either source to force a match.
