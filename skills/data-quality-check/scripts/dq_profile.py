#!/usr/bin/env python3
"""Profile a CSV and run data-quality checks. Writes a Markdown report and a JSON file.

  dq_profile.py data.csv [--key a,b] [--date-order start:end ...] [--non-negative col ...] [--required col ...] --out PATH
"""
import argparse, json, re
from datetime import datetime
import duckdb


def q(con, sql):
    return con.execute(sql).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv"); ap.add_argument("--out", required=True)
    ap.add_argument("--key"); ap.add_argument("--date-order", action="append", default=[])
    ap.add_argument("--non-negative", action="append", default=[]); ap.add_argument("--required", action="append", default=[])
    a = ap.parse_args()
    con = duckdb.connect()
    con.execute(f"CREATE TABLE t AS SELECT * FROM read_csv_auto('{a.csv}', header=true, sample_size=-1)")
    n = q(con, "SELECT count(*) FROM t")[0][0]
    cols = q(con, "DESCRIBE t")
    profile, findings = [], []

    def finding(check, severity, rows, detail, example=None):
        findings.append({"check": check, "severity": severity, "rows": rows, "share_pct": round(100 * rows / n, 3) if n else 0,
                         "detail": detail, "example": example})

    for name, typ, *_ in cols:
        c = f'"{name}"'
        nulls, distinct = q(con, f"SELECT count(*) - count({c}), count(DISTINCT {c}) FROM t")[0]
        p = {"column": name, "type": typ, "missing": nulls, "missing_pct": round(100 * nulls / n, 2) if n else 0, "distinct": distinct}
        if any(k in typ for k in ("INT", "DOUBLE", "DECIMAL", "FLOAT")):
            mn, mx, med, q1, q3 = q(con, f"SELECT min({c}), max({c}), median({c}), quantile_cont({c}, 0.25), quantile_cont({c}, 0.75) FROM t")[0]
            p.update(min=mn, max=mx, median=med)
            is_label = re.search(r"(zip|code|_id$|^id$|key|number|year|fips|lat|lng|lon)", name, re.I)   # identifiers, not quantities
            if not is_label and q1 is not None and q3 is not None and q3 > q1:
                hi = q3 + 3 * (q3 - q1); lo = q1 - 3 * (q3 - q1)
                out = q(con, f"SELECT count(*) FROM t WHERE {c} > {hi} OR {c} < {lo}")[0][0]
                if out:
                    p["extreme_outliers"] = out
        elif "DATE" in typ or "TIMESTAMP" in typ:
            mn, mx = q(con, f"SELECT min({c}), max({c}) FROM t")[0]
            p.update(min=str(mn), max=str(mx))
            fut = q(con, f"SELECT count(*) FROM t WHERE {c} > now()")[0][0]
            if fut:
                finding("future_dates", "error", fut, f"{name} is in the future")
        else:
            top = q(con, f"SELECT {c}, count(*) FROM t GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
            p["top_values"] = [[str(v), k] for v, k in top]
            blank = q(con, f"SELECT count(*) FROM t WHERE trim(CAST({c} AS VARCHAR)) = ''")[0][0]
            if blank:
                finding("blank_strings", "warning", blank, f"{name} has empty strings (not NULL)")
        if name in a.required and nulls:
            finding("required_missing", "error", nulls, f"{name} is required but missing")
        elif nulls and p["missing_pct"] >= 5:
            finding("high_missing", "warning", nulls, f"{name} is missing in {p['missing_pct']} percent of rows")
        profile.append(p)

    if a.key:
        keys = ", ".join(f'"{k}"' for k in a.key.split(","))
        dup = q(con, f"SELECT count(*), any_value(k) FROM (SELECT {keys}, CAST(({keys}) AS VARCHAR) AS k FROM t GROUP BY ALL HAVING count(*) > 1)")[0]
        if dup[0]:
            finding("duplicate_keys", "error", dup[0], f"{a.key} is not unique", dup[1])
    for pair in a.date_order:
        s, e = pair.split(":")
        bad = q(con, f'SELECT count(*), any_value(CAST(t AS VARCHAR)) FROM t WHERE "{e}" < "{s}"')[0]
        if bad[0]:
            finding("date_order", "error", bad[0], f"{e} is before {s}", bad[1][:300] if bad[1] else None)
    for c in a.non_negative:
        neg = q(con, f'SELECT count(*), min("{c}") FROM t WHERE "{c}" < 0')[0]
        if neg[0]:
            finding("negative_values", "error", neg[0], f"{c} is negative (minimum {neg[1]})")
    for p in profile:
        if p.get("extreme_outliers"):
            finding("extreme_outliers", "warning", p["extreme_outliers"], f"{p['column']} has values beyond 3 IQR (max {p['max']})")

    findings.sort(key=lambda f: (f["severity"] != "error", -f["rows"]))
    report = {"file": a.csv, "rows": n, "columns": len(cols), "checked_at": datetime.now().isoformat(timespec="seconds"),
              "findings": findings, "profile": profile}
    json.dump(report, open(a.out + ".json", "w"), indent=2, default=str)
    md = [f"# Data-quality report: {a.csv.rsplit('/', 1)[-1]}", "", f"{n:,} rows, {len(cols)} columns. Checked {report['checked_at']}.", "",
          "## Findings", ""]
    if findings:
        md += ["| Severity | Check | Rows | Share | Detail |", "|---|---|---:|---:|---|"]
        md += [f"| {f['severity']} | {f['check']} | {f['rows']:,} | {f['share_pct']}% | {f['detail']} |" for f in findings]
    else:
        md.append("No problems found by the automated checks.")
    md += ["", "## Column profile", "", "| Column | Type | Missing | Distinct | Range or top values |", "|---|---|---:|---:|---|"]
    for p in profile:
        rng = f"{p.get('min')} to {p.get('max')}" if "min" in p else ", ".join(f"{v} ({k:,})" for v, k in p.get("top_values", [])[:3])
        md.append(f"| {p['column']} | {p['type']} | {p['missing_pct']}% | {p['distinct']:,} | {rng[:120]} |")
    open(a.out + ".md", "w").write("\n".join(md) + "\n")
    print(f"{n:,} rows. {len(findings)} findings:")
    for f in findings:
        print(f"  [{f['severity']}] {f['check']}: {f['rows']:,} rows ({f['share_pct']}%) {f['detail']}")
    print(f"report -> {a.out}.md  data -> {a.out}.json")


if __name__ == "__main__":
    main()
