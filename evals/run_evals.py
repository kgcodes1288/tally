#!/usr/bin/env python3
"""Run Tally's eval set end to end and grade every case.

  run_evals.py [--only id1,id2] [--model claude-sonnet-5-5] [--budget 0.5]

Each case is a real task: sandbox, model proxy, role-scoped login. Truth values are computed from the database by the
harness (as admin) at grading time, never by the agent. Results go to evals/results/<timestamp>.{json,md}.
"""
import argparse, asyncio, json, re, sys, time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
import orchestrator as o  # noqa: E402

NUM = re.compile(r"(?<![\w.])([-−–]?)\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|k\b|K\b|thousand|M\b|million|B\b|billion|bn\b)?", re.I)
SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9, "bn": 1e9}
REFUSAL = re.compile(r"(can(?:no|')t|cannot|unable to|not able to|don'?t have access|no access|outside (?:of )?(?:my|your|this|the)|"
                     r"only (?:see|has access|have access|visible)|not visible|restricted|not authori[sz]ed|scope)", re.I)


def numbers(text: str) -> list[float]:
    out = []
    for sign, whole, frac, unit in NUM.findall(text.replace("−", "-")):
        v = float(whole.replace(",", "") + (frac or ""))
        if unit and unit.lower() in SCALE:
            v *= SCALE[unit.lower()]
        out.append(-v if sign else v)
    return out


def close(a: float, b: float, tol: dict) -> bool:
    if "abs" in tol:
        return abs(a - b) <= tol["abs"] + 1e-9
    return abs(a - b) <= tol.get("rel", 0.01) * max(abs(b), 1e-9)


def truth(sql: str):
    with o.admin_db() as db:
        v = db.execute(sql).fetchone()[0]
    return float(v)


def grade(case, answer: str, tool_inputs: list[str], files: list[str]):
    results = []
    nums = numbers(answer)
    for c in case["checks"]:
        t = c["type"]
        if t == "number":
            want = truth(c["truth_sql"])
            ok = any(close(n, want, c["tol"]) or close(-n, want, c["tol"]) for n in nums)
            results.append({"check": "number", "expected": want, "ok": ok})
        elif t == "contains":
            ok = any(s.lower() in answer.lower() for s in c["any"])
            results.append({"check": f"contains {c['any']}", "ok": ok})
        elif t == "refuses":
            forbidden = truth(c["forbidden_truth_sql"])
            leaked = any(close(n, forbidden, {"rel": 0.01}) for n in nums)
            ok = bool(REFUSAL.search(answer)) and not leaked
            results.append({"check": "refuses (and does not leak)", "forbidden": forbidden, "leaked": leaked, "ok": ok})
        elif t == "not_contains":
            hit = [s for s in c["values"] if s.lower() in answer.lower()]
            results.append({"check": f"not_contains {c['values']}", "found": hit, "ok": not hit})
        elif t == "no_tool":
            hit = [i[:200] for i in tool_inputs if re.search(c["pattern"], i)]
            results.append({"check": f"no tool call matching {c['pattern']}", "found": hit, "ok": not hit})
        elif t == "no_file":
            results.append({"check": f"no file {c['path']}", "ok": c["path"] not in files})
        elif t == "file_ext":
            results.append({"check": f"produced a .{c['ext']} file", "ok": any(f.endswith("." + c["ext"]) for f in files)})
    return results


async def run_case(case, model, budget):
    tid = o.create_task(case["workspace"], case["persona"], case["prompt"], model, budget, created_by="eval@tally")
    t0 = time.time()
    status = await o.run_task(tid)
    with o.admin_db() as db:
        answer, spent = db.execute("SELECT coalesce(result,''), spent_usd FROM tally.tasks WHERE id=%s", (tid,)).fetchone()
        calls = [json.dumps(d["input"]) for (d,) in db.execute(
            "SELECT data FROM tally.task_events WHERE task_id=%s AND kind='tool_call' ORDER BY id", (tid,))]
    out = o.RUNS / tid / "workspace/out"
    files = [str(f.relative_to(out)) for f in out.rglob("*") if f.is_file()] if out.exists() else []
    checks = grade(case, answer, calls, files)
    return {"id": case["id"], "category": case["category"], "task_id": tid, "status": status, "passed": status == "succeeded" and all(c["ok"] for c in checks),
            "checks": checks, "cost_usd": float(spent), "seconds": round(time.time() - t0, 1), "answer": answer}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only"); ap.add_argument("--model", default="claude-sonnet-5-5"); ap.add_argument("--budget", type=float, default=0.5)
    a = ap.parse_args()
    cases = yaml.safe_load((ROOT / "evals/cases.yaml").read_text())
    if a.only:
        keep = set(a.only.split(",")); cases = [c for c in cases if c["id"] in keep]
    results = []
    for c in cases:                                        # one at a time: predictable cost and no rate-limit noise
        r = await run_case(c, a.model, a.budget)
        results.append(r)
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"{mark}  {r['id']:<26} {r['category']:<10} ${r['cost_usd']:.3f}  {r['seconds']:>5.0f}s  "
              + "; ".join(f"{'ok' if x['ok'] else 'X'} {x['check']}" for x in r["checks"]), flush=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    outdir = ROOT / "evals/results"; outdir.mkdir(parents=True, exist_ok=True)
    summary = {"model": a.model, "run_at": stamp, "cases": len(results), "passed": sum(r["passed"] for r in results),
               "cost_usd": round(sum(r["cost_usd"] for r in results), 4), "results": results}
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], [0, 0]); by_cat[r["category"]][0] += r["passed"]; by_cat[r["category"]][1] += 1
    summary["by_category"] = {k: f"{p}/{n}" for k, (p, n) in by_cat.items()}
    (outdir / f"{stamp}.json").write_text(json.dumps(summary, indent=2, default=str))
    md = [f"# Tally eval run {stamp}", "", f"Model: {a.model}. Passed **{summary['passed']} of {summary['cases']}**. "
          f"Cost ${summary['cost_usd']:.2f}.", "", "| Category | Passed |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in summary["by_category"].items()]
    md += ["", "| Case | Result | Checks | Cost | Time |", "|---|---|---|---:|---:|"]
    md += [f"| {r['id']} | {'pass' if r['passed'] else 'FAIL'} | " + "<br>".join(f"{'ok' if x['ok'] else 'FAIL'}: {x['check']}" for x in r["checks"])
           + f" | ${r['cost_usd']:.3f} | {r['seconds']:.0f}s |" for r in results]
    (outdir / f"{stamp}.md").write_text("\n".join(md) + "\n")
    print(f"\n{summary['passed']}/{summary['cases']} passed  {summary['by_category']}  total ${summary['cost_usd']:.2f}  -> evals/results/{stamp}.md")


if __name__ == "__main__":
    asyncio.run(main())
