"""Runs one Tally task inside its sandbox.

Reads the task from environment and /task/prompt.txt, runs the Claude Agent SDK with Tally's tools, and writes
every event to stdout as one JSON object per line (the platform turns these into the live timeline).

Steering: the platform drops messages into /task/inbox/*.json while the task runs. A PostToolUse hook picks them
up and attaches them to the next tool result, so the agent reads them at its next step without being stopped.
Stop: the platform sends SIGUSR1, which becomes a clean SDK interrupt.
"""
import asyncio, json, os, shutil, signal, sys, time
from pathlib import Path

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, ResultMessage,
                              SystemMessage, TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock, UserMessage)
from tally_tools import TOOL_NAMES, server

INBOX = Path("/task/inbox"); INBOX.mkdir(parents=True, exist_ok=True)
OUT = Path("/workspace/out"); OUT.mkdir(parents=True, exist_ok=True)
BUILTIN = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
SKILLS = ["reconcile-sources", "data-quality-check", "html-dashboard", "pdf-report"]


def emit(kind, **data):
    print(json.dumps({"kind": kind, "ts": time.time(), "data": data}, default=str), flush=True)


SYSTEM = """
You are Tally, a data analyst agent working for one person inside an isolated sandbox.

Workspace: {ws_name} ({ws})
You are acting for: {persona}
Rows visible to this persona: {scope}

How to work:
- Start by calling whoami and list_tables. Check search_knowledge for definitions, playbooks and rules before you choose a method, and cite the passages you rely on.
- Query with run_sql for aggregates and small results. Use export_query to pull larger results into /workspace/data, then analyse with Python (pandas, DuckDB) via Bash.
- You can only see this persona's rows. If the question needs data outside that scope, say so plainly rather than guessing.
- Use your skills (reconcile-sources, data-quality-check, html-dashboard, pdf-report) whenever the task matches them; their scripts are tested, so prefer them over writing your own.
- Put every deliverable the person should receive (CSV, HTML dashboard, PDF, Markdown) in /workspace/out. Keep scratch files in /workspace/data.
- Be precise with numbers: state units, periods and filters. Prefer exact SQL totals over estimates.
- The person may send you notes while you work. They arrive marked "Message from the person you are working for". Treat them as instructions from that person and adjust.
- Finish with a concise answer: the result first, then how you got it, the files you produced, and any caveats or data-quality issues.
"""


def note_hook_factory():
    async def deliver_notes(input_data, tool_use_id, context):
        files = sorted(INBOX.glob("*.json"))
        if not files:
            return {}
        notes = []
        for f in files:
            try:
                m = json.loads(f.read_text())
                notes.append(m["body"])
                emit("steer_delivered", message_id=m["id"], after_tool=input_data.get("tool_name"))
            finally:
                f.unlink(missing_ok=True)
        text = "\n".join(f"Message from the person you are working for (sent while you were working): {n}" for n in notes)
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}
    return deliver_notes


async def main():
    prompt = Path("/task/prompt.txt").read_text()
    # Tally's skills ship read-only in the image; each task gets its own copy where the SDK discovers project skills.
    shutil.copytree("/opt/tally/skills", "/workspace/.claude/skills", dirs_exist_ok=True)
    env = os.environ
    options = ClaudeAgentOptions(
        model=env["TALLY_MODEL"],
        system_prompt={"type": "preset", "preset": "claude_code", "append": SYSTEM.format(
            ws=env["TALLY_WORKSPACE"], ws_name=env.get("TALLY_WORKSPACE_NAME", ""), persona=env.get("TALLY_PERSONA_TITLE", ""),
            scope=env.get("TALLY_SCOPE_DESC", ""))},
        cwd="/workspace",
        tools=BUILTIN + ["Skill"],                       # no web tools: the sandbox has no internet anyway
        allowed_tools=BUILTIN + ["Skill"] + TOOL_NAMES,
        skills=SKILLS,                                   # only Tally's own skills, never bundled ones
        disallowed_tools=["WebFetch", "WebSearch"],
        permission_mode="dontAsk",                       # anything not pre-approved is denied, never prompted
        mcp_servers={"tally": server},
        setting_sources=["project"],                     # needed to discover /workspace/.claude/skills; nothing else lives there
        max_turns=int(env.get("TALLY_MAX_TURNS", "40")),
        max_budget_usd=float(env.get("TALLY_BUDGET_USD", "0.5")),
        hooks={"PostToolUse": [HookMatcher(hooks=[note_hook_factory()])]},
    )
    emit("status", status="running", model=env["TALLY_MODEL"])
    async with ClaudeSDKClient(options=options) as client:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGUSR1, lambda: (emit("status", status="stopping"), asyncio.ensure_future(client.interrupt())))
        await client.query(prompt)
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock) and b.text.strip():
                        emit("text", text=b.text)
                    elif isinstance(b, ThinkingBlock) and b.thinking.strip():
                        emit("thinking", text=b.thinking)
                    elif isinstance(b, ToolUseBlock):
                        emit("tool_call", id=b.id, name=b.name.removeprefix("mcp__tally__"), input=b.input)
            elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
                for b in msg.content:
                    if isinstance(b, ToolResultBlock):
                        content = b.content if isinstance(b.content, str) else "\n".join(
                            c.get("text", "") for c in (b.content or []) if isinstance(c, dict))
                        emit("tool_result", id=b.tool_use_id, is_error=bool(getattr(b, "is_error", False)), text=content[:4000])
            elif isinstance(msg, SystemMessage) and msg.subtype == "init":
                emit("system", subtype="init", skills=[k for k in (msg.data.get("skills") or []) if k in SKILLS])
            elif isinstance(msg, SystemMessage) and msg.subtype != "thinking_tokens":
                emit("system", subtype=msg.subtype)
            elif isinstance(msg, ResultMessage):
                for f in sorted(OUT.rglob("*")):
                    if f.is_file():
                        emit("artifact", path=str(f.relative_to(OUT)), bytes=f.stat().st_size)
                emit("result", subtype=msg.subtype, is_error=msg.is_error, text=msg.result, turns=msg.num_turns,
                     duration_ms=msg.duration_ms, sdk_cost_usd=msg.total_cost_usd, terminal_reason=msg.terminal_reason)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:                                # report, never die silently
        emit("error", message=f"{type(e).__name__}: {e}")
        sys.exit(1)
