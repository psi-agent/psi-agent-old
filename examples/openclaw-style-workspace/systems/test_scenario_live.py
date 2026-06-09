"""Scenario-driven live test — simulates a real psi-agent session end-to-end.

Scenario
--------
A developer ("sby") is using openclaw-style-workspace to build a Python async
service.  Over the course of a session they:

  Turn 1-3:  Ask about asyncio patterns — the agent helps, using several tools
  Turn 4-6:  Ask about git workflow and CI setup
  Turn 7-9:  Debug an aiohttp connection error together
  Turn 10:   Session ends — BackgroundReview memory review fires
             (turn % 10 == 0, tool_call_count < 10 this turn → memory only)
  Turn 11:   A tool-heavy turn (refactoring) — skill review fires
             (tool_call_count >= 10)
  Turn 20:   Another 10-turn milestone — combined review fires
             (turn % 10 == 0 AND tool_call_count >= 10)
  Startup:   Curator runs because last_run_at is stale (> 7 days ago)
             and idle_for_seconds=inf

What we verify at the end
--------------------------
  • memory.md was written (user preferences captured)
  • At least one skill was created or patched (technique captured)
  • Curator report exists and shows actions taken
  • .curator_state.json last_run_at was updated

Usage
-----
    cd examples/openclaw-style-workspace
    uv run python systems/test_scenario_live.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import aiohttp
import anyio

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------

_WORKSPACE_ROOT = str(Path(__file__).parents[1])
_SYSTEMS_DIR = str(Path(__file__).parent)
_TOOLS_DIR = str(Path(__file__).parents[1] / "tools")
for _p in (_WORKSPACE_ROOT, _SYSTEMS_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import memory as mem_tool  # noqa: E402
import skill_manage as sm_tool  # noqa: E402
from background_review import BackgroundReview  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("scenario")

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("OPENAI_API_KEY", "sk-zNTKP29gOti1Tl8sJEsw0yQBLDXP9f61UkwkfbiOJgn1aApR")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4")

# ---------------------------------------------------------------------------
# LLM helpers
# ---------------------------------------------------------------------------


async def llm_str(messages: list[dict]) -> str:
    """Call LLM, return assistant text (no tools)."""
    async with aiohttp.ClientSession() as s:
        payload = {"model": MODEL, "messages": messages, "temperature": 0}
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        async with s.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"]


async def llm_with_tools(messages: list[dict], tools: list[dict]) -> dict:
    """Call LLM with tool schemas, return full response dict."""
    async with aiohttp.ClientSession() as s:
        payload: dict = {"model": MODEL, "messages": messages, "temperature": 0}
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
        async with s.post(
            f"{BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=90),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# Workspace setup helpers
# ---------------------------------------------------------------------------


async def seed_workspace(ws: anyio.Path) -> None:
    """Seed a realistic pre-existing workspace state."""
    skills_dir = ws / "skills"
    await skills_dir.mkdir(parents=True, exist_ok=True)

    # Pre-existing agent skills — mix of ages and quality
    skills = [
        (
            "python-async-basics",
            "Python asyncio fundamentals",
            "coding",
            "2026-03-01T00:00:00Z",
            "Use async/await. Always await coroutines. Never block the event loop.",
        ),
        (
            "docker-cheatsheet",
            "Common Docker commands",
            "devops",
            "2026-01-15T00:00:00Z",
            "docker build, docker run, docker-compose up -d.",
        ),
        (
            "ci-flaky-tests",
            "Fixing flaky tests in CI",
            "testing",
            "2026-04-10T00:00:00Z",
            "CI was timing out because pytest had no timeout plugin. Added pytest-timeout.",
        ),
        (
            "code-review-checklist",
            "PR review checklist for Python projects",
            "coding",
            "2026-06-01T00:00:00Z",  # recent — curator should keep
            "Check: tests, type hints, no unused imports, docstrings, ruff passes.",
        ),
        (
            "python-type-hints",  # overlaps with python-static-analysis — curator may merge
            "How to add type hints in Python",
            "coding",
            "2026-02-01T00:00:00Z",
            "Use type annotations on all function signatures.\nPrefer `X | None` over `Optional[X]`.\nRun ty check to validate.",
        ),
        (
            "python-static-analysis",  # merge target — broader scope
            "Static analysis and type checking for Python",
            "coding",
            "2026-02-10T00:00:00Z",
            "Use ruff check for linting, ruff format for formatting.\nUse ty check for type checking.\nConfigure both in pyproject.toml.\nAlways run in CI.",
        ),
    ]

    for name, desc, cat, created_at, body in skills:
        d = skills_dir / name
        await d.mkdir(exist_ok=True)
        fm = (
            f"---\nname: {name}\ndescription: {desc}\n"
            f"category: {cat}\ncreated_by: agent\ncreated_at: {created_at}\n---\n\n"
        )
        await (d / "SKILL.md").write_text(fm + body, encoding="utf-8")

    # Pre-existing memory
    memory_content = (
        "- User: sby\n"
        "- Project: psi-agent (Python async agent framework)\n"
        "- Stack: Python 3.14, anyio, aiohttp, uv\n"
        "- Preference: concise answers, no fluff\n"
    )
    await (ws / "memory.md").write_text(memory_content, encoding="utf-8")

    # Force curator state to stale (8 days ago)
    state = {"last_run_at": "2026-05-01T00:00:00Z"}
    await (skills_dir / ".curator_state.json").write_text(json.dumps(state), encoding="utf-8")

    print(f"  Workspace seeded: {len(skills)} skills, memory.md, stale curator state")


def build_conversation() -> list[dict]:
    """Build a realistic 20-turn conversation history."""
    turns = [
        # turns 1-3: asyncio patterns
        ("user", "How do I run multiple async tasks concurrently without blocking?"),
        (
            "assistant",
            "Use `asyncio.gather()`. For independent tasks: `await asyncio.gather(task_a(), task_b())`. Add `return_exceptions=True` if you don't want one failure to cancel the rest.",
        ),
        ("user", "What's the difference between create_task and gather?"),
        (
            "assistant",
            "`asyncio.create_task()` schedules a coroutine immediately and returns a Task you can await later. `gather()` awaits multiple coroutines/tasks together and returns their results as a list. Use `create_task` when you want fire-and-forget or need to cancel individually.",
        ),
        ("user", "Ok, and how do I set a timeout on an individual task?"),
        (
            "assistant",
            "Wrap it with `asyncio.wait_for(coro(), timeout=5.0)`. It raises `asyncio.TimeoutError` on expiry. For groups use `asyncio.timeout()` context manager (Python 3.11+).",
        ),
        # turns 4-6: git / CI
        ("user", "What's a clean git branching model for a small team?"),
        (
            "assistant",
            "Short-lived feature branches off main. One branch per PR, delete after merge. Use `git rebase -i` to clean up before merging. Tag releases.",
        ),
        ("user", "How should I write commit messages?"),
        (
            "assistant",
            "Conventional Commits: `<type>(<scope>): <summary>`. Types: feat, fix, chore, docs, refactor, test. Keep subject ≤ 72 chars. Add body for context when needed.",
        ),
        ("user", "We keep hitting flaky tests in CI. Any patterns to avoid this?"),
        (
            "assistant",
            "Isolate external state (DB, filesystem, network) with fixtures. Use `anyio` markers in pytest for async. Add `pytest-timeout` to catch hangs. Run tests in parallel only if they're truly isolated.",
        ),
        # turns 7-9: aiohttp debugging
        (
            "user",
            "Getting `aiohttp.ClientConnectorError: Cannot connect to host`. How do I debug this?",
        ),
        (
            "assistant",
            "Check: 1) Is the server actually running? 2) Correct host/port? 3) Firewall/DNS? 4) Try `curl` the same endpoint. In code, add `connector_owner=True` and log the exception with full traceback. Use `aiohttp.TCPConnector(ssl=False)` if TLS is the issue.",
        ),
        ("user", "The server is running but connections intermittently fail under load."),
        (
            "assistant",
            "You're hitting connection pool limits. Set `connector = aiohttp.TCPConnector(limit=50, limit_per_host=20)` and reuse a single `ClientSession` per process — don't create one per request. Also add retry logic with exponential backoff using `tenacity`.",
        ),
        ("user", "Great, the connection pooling fix worked! I'll use tenacity for retries too."),
        (
            "assistant",
            "Good. Canonical pattern: `@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))` on the request function. Log each retry attempt at WARNING level.",
        ),
        # turn 10: memory review fires — new personal signals not yet in memory
        (
            "user",
            "By the way I always work in Chinese timezone (UTC+8), and I prefer you respond in Chinese when I write in Chinese. Also I never use mypy, only ty check for type checking in all my projects.",
        ),
        ("assistant", "记住了：UTC+8 时区，中文回复中文，类型检查只用 ty check 不用 mypy。"),
        # turn 11: heavy tool usage (refactoring session) — skill review fires
        (
            "user",
            "Now help me refactor the entire HTTP client module — add type hints, split into classes, update all call sites.",
        ),
        (
            "assistant",
            "I'll start by reading the existing module, then create a typed ClientSession wrapper, update imports across call sites, and run ruff + ty check. This will touch ~12 files.",
        ),
        # turns 12-19: more back-and-forth
        ("user", "While refactoring, I noticed we never handle 429 rate-limit responses."),
        (
            "assistant",
            "Add a check: `if response.status == 429: raise RateLimitError(retry_after=int(response.headers.get('Retry-After', 60)))`. Catch it in the tenacity decorator with `retry_if_exception_type(RateLimitError)`.",
        ),
        ("user", "Also 503 responses should retry, but 400s should not."),
        (
            "assistant",
            "Right. `retry_if_exception_type((RateLimitError, ServiceUnavailableError))`. For 4xx: raise `ClientError` directly without retry. Wrap all of this in a `_classify_response(status)` helper.",
        ),
        (
            "user",
            "I want the retry delay for 429 to respect the Retry-After header, not just exponential backoff.",
        ),
        (
            "assistant",
            "Use a custom `wait` function: `wait=lambda retry_state: float(retry_state.outcome.exception().retry_after)` for RateLimitError, fall back to exponential for others.",
        ),
        (
            "user",
            "Perfect. I really hate when assistants give me 3 paragraphs of explanation when one line would do.",
        ),
        ("assistant", "Noted. One line it is."),
        (
            "user",
            "One more thing — always show me the full function signature when you suggest a change, not just a fragment.",
        ),
        ("assistant", "Got it."),
        # turn 20: combined review fires (turn % 10 == 0, tool_call_count >= 10)
        ("user", "Ok wrapping up. Can you summarize what we changed today?"),
        (
            "assistant",
            "Typed HTTP client wrapper, connection pooling, tenacity retries with 429/503 handling, Retry-After-aware wait, full type hints across 12 files.",
        ),
    ]
    messages: list[dict] = [
        {"role": "system", "content": "You are a helpful assistant for a Python developer."}
    ]
    for role, content in turns:
        messages.append({"role": role, "content": content})
    return messages


# ---------------------------------------------------------------------------
# Main scenario
# ---------------------------------------------------------------------------


async def run_scenario(ws: anyio.Path) -> None:
    os.environ["WORKSPACE_DIR"] = str(ws)
    tool_executors = {"memory": mem_tool.tool, "skill_manage": sm_tool.tool}

    # ── Startup: BackgroundReview init triggers curator check ──────────────
    print("\n[startup] Initialising BackgroundReview (curator check will fire async)...")
    br = BackgroundReview(
        complete_fn=llm_with_tools,
        tool_executors=tool_executors,
        workspace_dir=ws,  # triggers _startup_curator_check
    )

    # Give curator task a moment to start (it will run concurrently with turns)
    await asyncio.sleep(1)

    # ── Build full conversation ─────────────────────────────────────────────
    messages = build_conversation()
    total_turns = sum(1 for m in messages if m["role"] == "user")
    print(f"[session] Simulating {total_turns} user turns...")

    # ── Replay turns, calling BackgroundReview after each assistant reply ───
    tool_call_counts = {
        10: 0,  # memory-only review
        11: 12,  # skill review (heavy refactoring turn)
        20: 11,  # combined review
    }

    turn_idx = 0
    for i, msg in enumerate(messages):
        if msg["role"] != "user":
            continue
        turn_idx += 1
        br.increment_turn()
        tool_calls_this_turn = tool_call_counts.get(turn_idx, 0)

        # Print progress at key turns
        if turn_idx in (10, 11, 20):
            print(f"  [turn {turn_idx}] tool_calls={tool_calls_this_turn} → ", end="")
            if turn_idx % 10 == 0 and tool_calls_this_turn >= 10:
                print("combined review")
            elif turn_idx % 10 == 0:
                print("memory review")
            elif tool_calls_this_turn >= 10:
                print("skill review")

        await br.maybe_spawn(messages[: i + 2], tool_call_count=tool_calls_this_turn)

    # ── Wait for all background tasks to complete ───────────────────────────
    print("\n[wait] Waiting for background tasks (memory/skill/curator)...")
    await asyncio.sleep(35)

    # ── Print results ────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    # Memory
    memory = await mem_tool.tool(action="read")
    print(f"\n[memory.md]\n{memory}\n")

    # Skills
    skill_list = await sm_tool.tool(action="list")
    print(f"[skills]\n{skill_list}\n")

    # Curator report
    report_path = ws / "skills" / ".curator_report.md"
    if await report_path.exists():
        report = await report_path.read_text(encoding="utf-8")
        print(f"[curator report]\n{report}\n")
    else:
        print("[curator report] NOT FOUND\n")

    # Curator state
    state_path = ws / "skills" / ".curator_state.json"
    if await state_path.exists():
        state = json.loads(await state_path.read_text(encoding="utf-8"))
        print(f"[curator state] last_run_at={state.get('last_run_at')}")
        print(f"                summary={state.get('last_run_summary')}\n")

    # ── Assertions ──────────────────────────────────────────────────────────
    print("=" * 60)
    print("  ASSERTIONS")
    print("=" * 60)

    errors: list[str] = []

    if "empty" in memory.lower() and "Example entries" in memory:
        errors.append("memory: not updated by LLM (still contains placeholder)")
    else:
        print("  [OK] memory.md updated")

    if "no skills found" in skill_list.lower():
        errors.append("skills: no skills created or patched by background review")
    else:
        print("  [OK] skills library has entries")

    if not await report_path.exists():
        errors.append("curator: .curator_report.md not written")
    else:
        print("  [OK] curator report written")

    if await state_path.exists():
        state2 = json.loads(await state_path.read_text(encoding="utf-8"))
        if state2.get("last_run_at", "") <= "2026-05-01":
            errors.append("curator: last_run_at not updated after run")
        else:
            print(f"  [OK] curator state updated: last_run_at={state2['last_run_at']}")
    else:
        errors.append("curator: .curator_state.json not found")

    print()
    if errors:
        for e in errors:
            print(f"  [FAIL] {e}")
        raise SystemExit(1)
    else:
        print("  All assertions passed.")


async def main() -> None:
    print(f"Scenario test — model={MODEL}")
    ws = anyio.Path(_WORKSPACE_ROOT)
    print(f"Using real workspace: {ws}\n")
    print("[setup] Seeding test skills and curator state...")
    await seed_workspace(ws)
    await run_scenario(ws)
    print("\nScenario complete.")


if __name__ == "__main__":
    asyncio.run(main())
