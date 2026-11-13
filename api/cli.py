#!/usr/bin/env python3
"""Run a Tally task from the terminal and watch it live.

  cli.py run WORKSPACE PERSONA "question" [--model claude-opus-5-5] [--budget 0.5] [--steer-after 30 "note"]
"""
import argparse, asyncio, sys, textwrap, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestrator as o

ICON = {"tool_call": ">>", "tool_result": "<<", "text": "  ", "thinking": "..", "usage": "$ ", "status": "##",
        "steer_queued": "->", "steer_delivered": "=>", "artifact": "[]", "result": "OK", "error": "!!", "log": "  "}


def show(kind, d):
    if kind == "tool_call":
        arg = d["input"].get("sql") or d["input"].get("query") or d["input"].get("command") or d["input"].get("file_path") or d["input"]
        line = f"{d['name']}: {str(arg)[:300]}"
    elif kind == "tool_result":
        line = ("ERROR " if d.get("is_error") else "") + d["text"].replace("\n", " | ")[:220]
    elif kind == "usage":
        line = f"{d['model']} in={d.get('input_tokens')} out={d.get('output_tokens')} cache_read={d.get('cache_read_input_tokens', 0)} task total=${d['task_spent_usd']:.4f}"
    elif kind == "result":
        line = f"{d.get('subtype')} in {d.get('turns')} turns, {d.get('duration_ms', 0) / 1000:.0f}s\n" + textwrap.indent(d.get("text") or "", "   ")
    else:
        line = d.get("text") or d.get("status") or d.get("path") or d.get("message") or d.get("body") or d.get("line") or str(d)
    print(f"{time.strftime('%H:%M:%S')} {ICON.get(kind, '  ')} {line}", flush=True)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd"); ap.add_argument("workspace"); ap.add_argument("persona"); ap.add_argument("prompt")
    ap.add_argument("--model", default="claude-sonnet-5-5"); ap.add_argument("--budget", type=float, default=0.5)
    ap.add_argument("--steer-after", nargs=2, metavar=("SECONDS", "NOTE"))
    a = ap.parse_args()
    tid = o.create_task(a.workspace, a.persona, a.prompt, a.model, a.budget)
    print(f"task {tid}  ({a.workspace} as {a.persona}, {a.model}, budget ${a.budget})")
    run = asyncio.create_task(o.run_task(tid, on_event=show))
    if a.steer_after:
        await asyncio.sleep(float(a.steer_after[0]))
        if not run.done():
            o.steer(tid, a.steer_after[1]); show("steer_queued", {"body": a.steer_after[1]})
    status = await run
    print(f"final status: {status}   outputs: {o.RUNS / tid / 'workspace/out'}")

asyncio.run(main())
