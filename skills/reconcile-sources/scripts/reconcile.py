#!/usr/bin/env python3
"""Match two CSVs on a key and classify every record: matched, left_only, right_only, amount_diff.

  reconcile.py --left L.csv --right R.csv --key id[,id2] --amount amt[,amt2] [--tolerance 0.01]
               [--left-name A] [--right-name B] --out /workspace/out/reconciliation
"""
import argparse, json
import duckdb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--left", required=True); ap.add_argument("--right", required=True)
    ap.add_argument("--key", required=True); ap.add_argument("--amount", required=True)
    ap.add_argument("--tolerance", type=float, default=0.01)
    ap.add_argument("--left-name", default="left"); ap.add_argument("--right-name", default="right")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    keys, amts = a.key.split(","), a.amount.split(",")
    con = duckdb.connect()
    for side, path in (("l", a.left), ("r", a.right)):
        con.execute(f"CREATE TABLE {side} AS SELECT * FROM read_csv_auto('{path}', header=true)")
        cols = [c[0] for c in con.execute(f"DESCRIBE {side}").fetchall()]
        missing = [c for c in keys + amts if c not in cols]
        if missing:
            raise SystemExit(f"{path} is missing columns {missing}; it has {cols}")
        dupes = con.execute(f"SELECT count(*) FROM (SELECT {', '.join(keys)} FROM {side} GROUP BY ALL HAVING count(*) > 1)").fetchone()[0]
        if dupes:
            raise SystemExit(f"{path} has {dupes} duplicate keys. Aggregate to one row per key before reconciling.")
    on = " AND ".join(f"l.{k} IS NOT DISTINCT FROM r.{k}" for k in keys)
    keysel = ", ".join(f"coalesce(l.{k}, r.{k}) AS {k}" for k in keys)
    amtsel = ", ".join(f"coalesce(l.{m}, 0)::DOUBLE AS left_{m}, coalesce(r.{m}, 0)::DOUBLE AS right_{m}, "
                       f"(coalesce(r.{m}, 0) - coalesce(l.{m}, 0))::DOUBLE AS diff_{m}" for m in amts)
    lk, rk = f"l.{keys[0]}", f"r.{keys[0]}"
    over = " OR ".join(f"abs(coalesce(r.{m},0) - coalesce(l.{m},0)) > {a.tolerance}" for m in amts)
    con.execute(f"""CREATE TABLE rec AS SELECT {keysel}, {amtsel},
                  CASE WHEN {rk} IS NULL THEN 'left_only' WHEN {lk} IS NULL THEN 'right_only'
                       WHEN {over} THEN 'amount_diff' ELSE 'matched' END AS status
                FROM l FULL OUTER JOIN r ON {on}""")
    first = amts[0]
    con.execute(f"COPY (SELECT * FROM rec WHERE status <> 'matched' ORDER BY abs(diff_{first}) DESC) TO '{a.out}_exceptions.csv' (HEADER)")
    by = con.execute(f"""SELECT status, count(*) AS records, round(sum(left_{first}), 2) AS left_total, round(sum(right_{first}), 2) AS right_total,
                            round(sum(diff_{first}), 2) AS net_diff, round(sum(abs(diff_{first})), 2) AS gross_diff
                     FROM rec GROUP BY 1 ORDER BY records DESC""").fetchall()
    tot = con.execute(f"SELECT count(*), round(sum(left_{first}),2), round(sum(right_{first}),2) FROM rec").fetchone()
    summary = {"left": a.left_name, "right": a.right_name, "key": keys, "amounts": amts, "tolerance": a.tolerance,
               "records": tot[0], "left_total": tot[1], "right_total": tot[2], "net_difference": round((tot[2] or 0) - (tot[1] or 0), 2),
               "by_status": [dict(zip(["status", "records", "left_total", "right_total", "net_diff", "gross_diff"], r)) for r in by],
               "reconciled": all(r[0] == "matched" for r in by)}
    json.dump(summary, open(f"{a.out}_summary.json", "w"), indent=2)
    print(f"{a.left_name} total {tot[1]:,} vs {a.right_name} total {tot[2]:,} (net difference {summary['net_difference']:,}) over {tot[0]:,} keys")
    print(f"{'status':<12} {'records':>9} {'net_diff':>16} {'gross_diff':>16}")
    for r in by:
        print(f"{r[0]:<12} {r[1]:>9,} {r[4]:>16,} {r[5]:>16,}")
    print(f"exceptions -> {a.out}_exceptions.csv   summary -> {a.out}_summary.json")


if __name__ == "__main__":
    main()
