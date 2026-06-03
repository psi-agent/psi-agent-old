"""Hermes-style system prompt assembly for psi-agent workspace.

Implements the three-tier system prompt architecture inspired by Hermes Agent:

* ``stable``   — identity (SOUL.md or DEFAULT_AGENT_IDENTITY), task-completion
  guidance, tool-use enforcement guidance, per-model operational guidance,
  skills index, environment hints.
* ``context``  — project context files discovered under cwd
  (.hermes.md / HERMES.md / AGENTS.md / CLAUDE.md / .cursorrules).
* ``volatile`` — current date, model name.

Three tiers are joined with ``\\n\\n``, empty tiers are skipped.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import platform
import re
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import anyio
from systems.threat_patterns import scan_for_threats

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

CompleteFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

# ---------------------------------------------------------------------------
# Constants — identity & guidance (ported from Hermes Agent prompt_builder.py)
# ---------------------------------------------------------------------------

DEFAULT_AGENT_IDENTITY = (
    "You are a helpful AI assistant. "
    "You are helpful, knowledgeable, and direct. You assist users with a wide "
    "range of tasks including answering questions, writing and editing code, "
    "analyzing information, creative work, and executing actions via your tools. "
    "You communicate clearly, admit uncertainty when appropriate, and prioritize "
    "being genuinely useful over being verbose unless otherwise directed below. "
    "Be targeted and efficient in your exploration and investigations."
)

TASK_COMPLETION_GUIDANCE = (
    "# Finishing the job\n"
    "When the user asks you to build, run, or verify something, the deliverable is "
    "a working artifact backed by real tool output — not a description of one. "
    "Do not stop after writing a stub, a plan, or a single command. Keep working "
    "until you have actually exercised the code or produced the requested result, "
    "then report what real execution returned.\n"
    "If a tool, install, or network call fails and blocks the real path, say so "
    "directly and try an alternative (different package manager, different "
    "approach, ask the user). NEVER substitute plausible-looking fabricated "
    "output (made-up data, invented file contents, synthesised API responses) "
    "for results you couldn't actually produce. Reporting a blocker honestly "
    "is always better than inventing a result."
)

TOOL_USE_ENFORCEMENT_GUIDANCE = (
    "# Tool-use enforcement\n"
    "You MUST use your tools to take action — do not describe what you would do "
    "or plan to do without actually doing it. When you say you will perform an "
    "action (e.g. 'I will run the tests', 'Let me check the file', 'I will create "
    "the project'), you MUST immediately make the corresponding tool call in the same "
    "response. Never end your turn with a promise of future action — execute it now.\n"
    "Keep working until the task is actually complete. Do not stop with a summary of "
    "what you plan to do next time. If you have tools available that can accomplish "
    "the task, use them instead of telling the user what you would do.\n"
    "Every response should either (a) contain tool calls that make progress, or "
    "(b) deliver a final result to the user. Responses that only describe intentions "
    "without acting are not acceptable.\n"
    "\n"
    "<mandatory_tool_use>\n"
    "NEVER answer these from memory or mental computation — ALWAYS use a tool:\n"
    "- Arithmetic, math, calculations → use bash tool\n"
    "- Hashes, encodings, checksums → use bash tool (e.g. sha256sum, base64)\n"
    "- Current time, date, timezone → use bash tool (e.g. date)\n"
    "- System state: OS, CPU, memory, disk, ports, processes → use bash tool\n"
    "- File contents, sizes, line counts → use read tool or bash tool\n"
    "- Git history, branches, diffs → use bash tool\n"
    "</mandatory_tool_use>\n"
    "\n"
    "<act_dont_ask>\n"
    "When a question has an obvious default interpretation, act on it immediately "
    "instead of asking for clarification. Examples:\n"
    "- 'Is port 443 open?' → check THIS machine (don't ask 'open where?')\n"
    "- 'What OS am I running?' → check the live system\n"
    "- 'What time is it?' → run `date` (don't guess)\n"
    "Only ask for clarification when the ambiguity genuinely changes what tool "
    "you would call.\n"
    "</act_dont_ask>\n"
    "\n"
    "<prerequisite_checks>\n"
    "- Before taking an action, check whether prerequisite discovery, lookup, or "
    "context-gathering steps are needed.\n"
    "- Do not skip prerequisite steps just because the final action seems obvious.\n"
    "- If a task depends on output from a prior step, resolve that dependency first.\n"
    "</prerequisite_checks>\n"
    "\n"
    "<verification>\n"
    "Before finalizing your response:\n"
    "- Correctness: does the output satisfy every stated requirement?\n"
    "- Grounding: are factual claims backed by tool outputs or provided context?\n"
    "- Formatting: does the output match the requested format or schema?\n"
    "- Safety: if the next step has side effects (file writes, commands, API calls), "
    "confirm scope before executing.\n"
    "</verification>\n"
    "\n"
    "<missing_context>\n"
    "- If required context is missing, do NOT guess or hallucinate an answer.\n"
    "- Use the appropriate lookup tool when missing information is retrievable.\n"
    "- Ask a clarifying question only when the information cannot be retrieved by tools.\n"
    "- If you must proceed with incomplete information, label assumptions explicitly.\n"
    "</missing_context>"
)

# Model name substrings that trigger tool-use enforcement guidance.
TOOL_USE_ENFORCEMENT_MODELS = (
    "gpt",
    "codex",
    "gemini",
    "gemma",
    "grok",
    "glm",
    "qwen",
    "deepseek",
)

OPENAI_MODEL_EXECUTION_GUIDANCE = (
    "# Execution discipline\n"
    "<tool_persistence>\n"
    "- Use tools whenever they improve correctness, completeness, or grounding.\n"
    "- Do not stop early when another tool call would materially improve the result.\n"
    "- If a tool returns empty or partial results, retry with a different query or "
    "strategy before giving up.\n"
    "- Keep calling tools until: (1) the task is complete, AND (2) you have verified "
    "the result.\n"
    "</tool_persistence>\n"
    "\n"
    "<prerequisite_checks>\n"
    "- Before taking an action, check whether prerequisite discovery, lookup, or "
    "context-gathering steps are needed.\n"
    "- Do not skip prerequisite steps just because the final action seems obvious.\n"
    "- If a task depends on output from a prior step, resolve that dependency first.\n"
    "</prerequisite_checks>"
)

GOOGLE_MODEL_OPERATIONAL_GUIDANCE = (
    "# Google model operational directives\n"
    "Follow these operational rules strictly:\n"
    "- **Absolute paths:** Always construct and use absolute file paths for all "
    "file system operations. Combine the project root with relative paths.\n"
    "- **Verify first:** Check file contents and project structure before making "
    "changes. Never guess at file contents.\n"
    "- **Dependency checks:** Never assume a library is available. Check "
    "package.json, requirements.txt, Cargo.toml, etc. before importing.\n"
    "- **Conciseness:** Keep explanatory text brief — a few sentences, not "
    "paragraphs. Focus on actions and results over narration.\n"
    "- **Parallel tool calls:** When you need to perform multiple independent "
    "operations, make all the tool calls in a single response rather than sequentially.\n"
    "- **Non-interactive commands:** Use flags like -y, --yes, --non-interactive "
    "to prevent CLI tools from hanging on prompts.\n"
    "- **Keep going:** Work autonomously until the task is fully resolved. "
    "Don't stop with a plan — execute it.\n"
)

# ---------------------------------------------------------------------------
# Platform hints — injected based on HERMES_PLATFORM env var
# ---------------------------------------------------------------------------

PLATFORM_HINTS: dict[str, str] = {
    "whatsapp": (
        "You are on a text messaging communication platform, WhatsApp. "
        "Please do not use markdown as it does not render. "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. The file "
        "will be sent as a native WhatsApp attachment — images (.jpg, .png, "
        ".webp) appear as photos, videos (.mp4, .mov) play inline, and other "
        "files arrive as downloadable documents. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as photos."
    ),
    "telegram": (
        "You are on a text messaging communication platform, Telegram. "
        "Standard markdown is automatically converted to Telegram format. "
        "Supported: **bold**, *italic*, ~~strikethrough~~, ||spoiler||, "
        "`inline code`, ```code blocks```, [links](url), and ## headers. "
        "Telegram has NO table syntax — prefer bullet lists or labeled "
        "key: value pairs over pipe tables (any tables you do emit are "
        "auto-rewritten into row-group bullets, which you can produce "
        "directly for cleaner output). "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. Images "
        "(.png, .jpg, .webp) appear as photos, audio (.ogg) sends as voice "
        "bubbles, and videos (.mp4) play inline. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as native photos."
    ),
    "discord": (
        "You are in a Discord server or group chat communicating with your user. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.png, .jpg, .webp) are sent as photo "
        "attachments, audio as file attachments. You can also include image URLs "
        "in markdown format ![alt](url) and they will be sent as attachments."
    ),
    "slack": (
        "You are in a Slack workspace communicating with your user. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.png, .jpg, .webp) are uploaded as photo "
        "attachments, audio as file attachments. You can also include image URLs "
        "in markdown format ![alt](url) and they will be uploaded as attachments."
    ),
    "signal": (
        "You are on a text messaging communication platform, Signal. "
        "Please do not use markdown as it does not render. "
        "You can send media files natively: to deliver a file to the user, "
        "include MEDIA:/absolute/path/to/file in your response. Images "
        "(.png, .jpg, .webp) appear as photos, audio as attachments, and other "
        "files arrive as downloadable documents. You can also include image "
        "URLs in markdown format ![alt](url) and they will be sent as photos."
    ),
    "email": (
        "You are communicating via email. Write clear, well-structured responses "
        "suitable for email. Use plain text formatting (no markdown). "
        "Keep responses concise but complete. You can send file attachments — "
        "include MEDIA:/absolute/path/to/file in your response. The subject line "
        "is preserved for threading. Do not include greetings or sign-offs unless "
        "contextually appropriate."
    ),
    "cron": (
        "You are running as a scheduled cron job. There is no user present — you "
        "cannot ask questions, request clarification, or wait for follow-up. Execute "
        "the task fully and autonomously, making reasonable decisions where needed. "
        "Your final response is automatically delivered to the job's configured "
        "destination — put the primary content directly in your response."
    ),
    "cli": (
        "You are a CLI AI Agent. Try not to use markdown but simple text "
        "renderable inside a terminal. "
        "File delivery: there is no attachment channel — the user reads your "
        "response directly in their terminal. Do NOT emit MEDIA:/path tags "
        "(those are only intercepted on messaging platforms like Telegram, "
        "Discord, Slack, etc.; on the CLI they render as literal text). "
        "When referring to a file you created or changed, just state its "
        "absolute path in plain text; the user can open it from there."
    ),
    "sms": (
        "You are communicating via SMS. Keep responses concise and use plain text "
        "only — no markdown, no formatting. SMS messages are limited to ~1600 "
        "characters, so be brief and direct."
    ),
    "bluebubbles": (
        "You are chatting via iMessage (BlueBubbles). iMessage does not render "
        "markdown formatting — use plain text. Keep responses concise as they "
        "appear as text messages. You can send media files natively: include "
        "MEDIA:/absolute/path/to/file in your response. Images (.jpg, .png, "
        ".heic) appear as photos and other files arrive as attachments."
    ),
    "mattermost": (
        "You are in a Mattermost workspace communicating with your user. "
        "Mattermost renders standard Markdown — headings, bold, italic, code "
        "blocks, and tables all work. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.jpg, .png, .webp) are uploaded as photo "
        "attachments, audio and video as file attachments. "
        "Image URLs in markdown format ![alt](url) are rendered as inline previews automatically."
    ),
    "matrix": (
        "You are in a Matrix room communicating with your user. "
        "Matrix renders Markdown — bold, italic, code blocks, and links work; "
        "the adapter converts your Markdown to HTML for rich display. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.jpg, .png, .webp) are sent as inline photos, "
        "audio (.ogg, .mp3) as voice/audio messages, video (.mp4) inline, "
        "and other files as downloadable attachments."
    ),
    "feishu": (
        "You are in a Feishu (Lark) workspace communicating with your user. "
        "Feishu renders Markdown in messages — bold, italic, code blocks, and "
        "links are supported. "
        "You can send media files natively: include MEDIA:/absolute/path/to/file "
        "in your response. Images (.jpg, .png, .webp) are uploaded and displayed "
        "inline, audio files as voice messages, and other files as attachments."
    ),
    "weixin": (
        "You are on Weixin/WeChat. Markdown formatting is supported, so you may "
        "use it when it improves readability, but keep the message compact and "
        "chat-friendly. You can send media files natively: include "
        "MEDIA:/absolute/path/to/file in your response. Images are sent as native "
        "photos, videos play inline when supported, and other files arrive as "
        "downloadable documents. You can also include image URLs in markdown "
        "format ![alt](url) and they will be downloaded and sent as native media when possible."
    ),
    "wecom": (
        "You are on WeCom (企业微信 / Enterprise WeChat). Markdown formatting is supported. "
        "You CAN send media files natively — to deliver a file to the user, include "
        "MEDIA:/absolute/path/to/file in your response. The file will be sent as a native "
        "WeCom attachment: images (.jpg, .png, .webp) are sent as photos (up to 10 MB), "
        "other files (.pdf, .docx, .xlsx, .md, .txt, etc.) arrive as downloadable documents "
        "(up to 20 MB), and videos (.mp4) play inline. Voice messages are supported but "
        "must be in AMR format — other audio formats are automatically sent as file attachments. "
        "You can also include image URLs in markdown format ![alt](url) and they will be "
        "downloaded and sent as native photos. Do NOT tell the user you lack file-sending "
        "capability — use MEDIA: syntax whenever a file delivery is appropriate."
    ),
    "qqbot": (
        "You are on QQ, a popular Chinese messaging platform. QQ supports markdown formatting "
        "and emoji. You can send media files natively: include MEDIA:/absolute/path/to/file in "
        "your response. Images are sent as native photos, and other files arrive as downloadable "
        "documents."
    ),
    "api_server": (
        "You're responding through an API server. The rendering layer is unknown — "
        "assume plain text. No markdown formatting (no asterisks, bullets, headers, "
        "code fences). Treat this like a conversation, not a document. Keep responses "
        "brief and natural."
    ),
}

# ---------------------------------------------------------------------------
# Context file constants
# ---------------------------------------------------------------------------

CONTEXT_FILE_MAX_CHARS = 20_000
CONTEXT_TRUNCATE_HEAD_RATIO = 0.7
CONTEXT_TRUNCATE_TAIL_RATIO = 0.2

# ---------------------------------------------------------------------------
# Helper: git root discovery
# ---------------------------------------------------------------------------


def _find_git_root(start: anyio.Path) -> anyio.Path | None:
    """Walk start and its parents looking for a .git directory.

    Args:
        start: Directory to start searching from.

    Returns:
        Directory containing .git, or None if not found.
    """
    import pathlib

    current = pathlib.Path(str(start)).resolve()
    for directory in [current, *current.parents]:
        if (directory / ".git").exists():
            return anyio.Path(str(directory))
    return None


# ---------------------------------------------------------------------------
# Helper: content truncation
# ---------------------------------------------------------------------------


def _truncate_content(content: str, filename: str, max_chars: int = CONTEXT_FILE_MAX_CHARS) -> str:
    """Head/tail truncation with a marker in the middle.

    Args:
        content: The text content to truncate.
        filename: Filename used in the truncation marker.
        max_chars: Maximum character limit before truncating.

    Returns:
        Truncated content with a marker, or original if within limit.
    """
    if len(content) <= max_chars:
        return content
    head_chars = int(max_chars * CONTEXT_TRUNCATE_HEAD_RATIO)
    tail_chars = int(max_chars * CONTEXT_TRUNCATE_TAIL_RATIO)
    head = content[:head_chars]
    tail = content[-tail_chars:]
    marker = (
        f"\n\n[...truncated {filename}: kept {head_chars}+{tail_chars} of "
        f"{len(content)} chars. Use file tools to read the full file.]\n\n"
    )
    return head + marker + tail


# ---------------------------------------------------------------------------
# Helper: YAML frontmatter stripping
# ---------------------------------------------------------------------------


def _strip_yaml_frontmatter(content: str) -> str:
    """Remove optional YAML frontmatter (--- delimited) from content.

    Args:
        content: Raw file content possibly containing YAML frontmatter.

    Returns:
        Content with frontmatter removed, or original if none found.
    """
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4 :].lstrip("\n")
            return body if body else content
    return content


# ---------------------------------------------------------------------------
# Stable tier helpers
# ---------------------------------------------------------------------------


async def _load_soul_md() -> str | None:
    """Load SOUL.md from ~/.hermes/SOUL.md and return its content, or None.

    Returns:
        Content of SOUL.md stripped and truncated, or None if not found/empty.
    """
    soul_path = anyio.Path(os.path.expanduser("~/.hermes/SOUL.md"))
    if not await soul_path.exists():
        return None
    try:
        content = (await soul_path.read_text(encoding="utf-8")).strip()
        if not content:
            return None
        return _truncate_content(content, "SOUL.md")
    except Exception:
        return None


async def _parse_skill_frontmatter(skill_md_path: anyio.Path) -> dict[str, str]:
    """Parse SKILL.md YAML frontmatter to extract name, description, category.

    Args:
        skill_md_path: Path to the SKILL.md file.

    Returns:
        Dict with keys 'name', 'description', 'category' (all may be empty strings).
    """
    try:
        content = await skill_md_path.read_text(encoding="utf-8")
    except Exception:
        return {"name": "", "description": "", "category": ""}

    frontmatter_match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not frontmatter_match:
        return {"name": "", "description": "", "category": ""}

    fm = frontmatter_match.group(1)

    def _extract(field: str) -> str:
        m = re.search(rf"^{field}:\s*(.+)$", fm, re.MULTILINE)
        return m.group(1).strip().strip("'\"") if m else ""

    name = _extract("name")
    description = _extract("description")
    category = _extract("category") or "general"

    # Cap description at 60 chars (Hermes convention)
    if len(description) > 60:
        description = description[:57] + "..."

    return {"name": name, "description": description, "category": category}


async def _build_skills_index(workspace_dir: anyio.Path) -> str:
    """Scan workspace skills/ directory and build <available_skills> index block.

    Uses a disk snapshot cache (.skills_prompt_snapshot.json) to avoid
    re-parsing SKILL.md files when nothing has changed.

    Args:
        workspace_dir: Path to the workspace root directory.

    Returns:
        Formatted skills index string, or empty string if no skills found.
    """
    skills_dir = workspace_dir / "skills"
    if not await skills_dir.exists():
        return ""

    # --- Build manifest (mtime_ns + size per SKILL.md) ---
    manifest: dict[str, dict[str, int]] = {}
    skill_dirs: list[anyio.Path] = []
    async for skill_path in skills_dir.iterdir():
        if not await skill_path.is_dir():
            continue
        skill_md = skill_path / "SKILL.md"
        if not await skill_md.exists():
            continue
        skill_dirs.append(skill_path)
        try:
            stat = await skill_md.stat()
            manifest[str(skill_md)] = {
                "mtime_ns": int(stat.st_mtime_ns),
                "size": int(stat.st_size),
            }
        except Exception:
            manifest[str(skill_md)] = {"mtime_ns": 0, "size": 0}

    if not manifest:
        return ""

    # --- Try loading snapshot from disk ---
    snapshot_path = workspace_dir / ".skills_prompt_snapshot.json"
    snapshot_version = 1

    async def _load_snapshot() -> dict[str, Any] | None:
        if not await snapshot_path.exists():
            return None
        try:
            raw = await snapshot_path.read_text(encoding="utf-8")
            data: dict[str, Any] = json.loads(raw)
            if data.get("version") != snapshot_version:
                return None
            if data.get("manifest") != manifest:
                return None
            return data
        except Exception:
            return None

    async def _save_snapshot(
        skills_list: list[dict[str, str]],
    ) -> None:
        try:
            data: dict[str, Any] = {
                "version": snapshot_version,
                "manifest": manifest,
                "skills": skills_list,
            }
            await snapshot_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    snapshot = await _load_snapshot()
    if snapshot is not None:
        skills_list: list[dict[str, str]] = snapshot["skills"]
    else:
        # Full scan
        skills_list = []
        for skill_path in skill_dirs:
            skill_md = skill_path / "SKILL.md"
            fm = await _parse_skill_frontmatter(skill_md)
            skills_list.append(
                {
                    "name": fm["name"] or skill_path.name,
                    "description": fm["description"],
                    "category": fm["category"],
                }
            )
        await _save_snapshot(skills_list)

    # --- Group by category and build index ---
    skills_by_category: dict[str, list[tuple[str, str]]] = {}
    for entry in skills_list:
        skills_by_category.setdefault(entry["category"], []).append(
            (entry["name"], entry["description"])
        )

    if not skills_by_category:
        return ""

    index_lines: list[str] = []
    for category in sorted(skills_by_category):
        index_lines.append(f"  {category}:")
        for name, desc in sorted(skills_by_category[category]):
            if desc:
                index_lines.append(f"    - {name}: {desc}")
            else:
                index_lines.append(f"    - {name}")

    return (
        "## Skills (mandatory)\n"
        "Before replying, scan the skills below. If a skill matches or is even partially relevant "
        "to your task, you MUST load it by reading the corresponding SKILL.md file and follow its "
        "instructions. Err on the side of loading — it is always better to have context you don't "
        "need than to miss critical steps, pitfalls, or established workflows.\n"
        "Skills contain specialized knowledge — tool-specific commands and proven workflows that "
        "outperform general-purpose approaches. Skills also encode the user's preferred approach, "
        "conventions, and quality standards.\n"
        "\n"
        "<available_skills>\n" + "\n".join(index_lines) + "\n"
        "</available_skills>\n"
        "\n"
        "Only proceed without loading a skill if genuinely none are relevant to the task."
    )


async def _detect_wsl() -> bool:
    """Detect if running inside WSL by reading /proc/version.

    Returns:
        True if running inside WSL, False otherwise.
    """
    proc_version = anyio.Path("/proc/version")
    with contextlib.suppress(OSError, Exception):
        if await proc_version.exists():
            content = await proc_version.read_text(encoding="utf-8", errors="ignore")
            if "microsoft" in content.lower():
                return True
    return False


async def _probe_tool_versions() -> list[str]:
    """Probe python3, uv, and pip version strings.

    Returns:
        List of non-empty version hint strings.
    """
    lines: list[str] = []
    tools = [
        ("python3", ["python3", "--version"]),
        ("uv", ["uv", "--version"]),
        ("pip", ["pip", "--version"]),
    ]
    for label, cmd in tools:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3)
            output = (stdout or stderr).decode(errors="replace").strip()
            first_line = output.splitlines()[0] if output else ""
            if first_line:
                lines.append(f"{label}: {first_line}")
        except Exception:
            pass
    return lines


async def _build_environment_hints() -> str:
    """Return environment-specific hints for the system prompt.

    Returns:
        Multi-line string describing the execution environment.
    """
    hints: list[str] = []

    host_lines: list[str] = []
    if sys.platform == "win32":
        host_lines.append(f"Host: Windows ({platform.release()})")
    elif sys.platform == "darwin":
        mac_ver = platform.mac_ver()[0]
        host_lines.append(f"Host: macOS ({mac_ver or platform.release()})")
    else:
        host_lines.append(f"Host: {platform.system()} ({platform.release()})")

    host_lines.append(f"User home directory: {os.path.expanduser('~')}")
    with contextlib.suppress(OSError):
        host_lines.append(f"Current working directory: {os.getcwd()}")

    hints.append("\n".join(host_lines))

    # WSL detection
    if await _detect_wsl():
        hints.append(
            "You are running inside WSL (Windows Subsystem for Linux). "
            "The Windows host filesystem is mounted under /mnt/ — "
            "/mnt/c/ is the C: drive, /mnt/d/ is D:, etc. "
            "The user's Windows files are typically at "
            "/mnt/c/Users/<username>/Desktop/, Documents/, Downloads/, etc. "
            "When the user references Windows paths or desktop files, translate "
            "to the /mnt/c/ equivalent. You can list /mnt/c/Users/ to discover "
            "the Windows username if needed."
        )

    # Tool version probe
    tool_lines = await _probe_tool_versions()
    if tool_lines:
        hints.append("\n".join(tool_lines))

    return "\n\n".join(hints)


async def _build_stable(workspace_dir: anyio.Path, model: str | None = None) -> str:
    """Build the stable tier of the system prompt.

    Args:
        workspace_dir: Path to the workspace root directory.
        model: Optional model name used for conditional guidance injection.

    Returns:
        Stable tier string.
    """
    parts: list[str] = []

    # 1. Identity: SOUL.md or default
    soul = await _load_soul_md()
    if soul:
        parts.append(soul)
    else:
        parts.append(DEFAULT_AGENT_IDENTITY)

    # 2. Task completion guidance (universal)
    parts.append(TASK_COMPLETION_GUIDANCE)

    # 3. Tool-use enforcement (conditional on model name)
    if model:
        model_lower = model.lower()
        if any(p in model_lower for p in TOOL_USE_ENFORCEMENT_MODELS):
            parts.append(TOOL_USE_ENFORCEMENT_GUIDANCE)
            # Model-family-specific guidance
            if "gemini" in model_lower or "gemma" in model_lower:
                parts.append(GOOGLE_MODEL_OPERATIONAL_GUIDANCE)
            if "gpt" in model_lower or "codex" in model_lower or "grok" in model_lower:
                parts.append(OPENAI_MODEL_EXECUTION_GUIDANCE)

    # 4. Skills index
    skills_index = await _build_skills_index(workspace_dir)
    if skills_index:
        parts.append(skills_index)

    # 5. Environment hints (async: includes WSL detection + tool version probe)
    env_hints = await _build_environment_hints()
    if env_hints:
        parts.append(env_hints)

    # 6. Platform hint (from HERMES_PLATFORM env var)
    platform_key = os.environ.get("HERMES_PLATFORM", "").strip().lower()
    if platform_key:
        hint = PLATFORM_HINTS.get(platform_key)
        if hint:
            parts.append(hint)

    return "\n\n".join(p.strip() for p in parts if p and p.strip())


# ---------------------------------------------------------------------------
# Context tier helpers
# ---------------------------------------------------------------------------


async def _load_hermes_md(cwd: anyio.Path) -> str:
    """Load .hermes.md or HERMES.md, walking from cwd up to git root.

    Search order: cwd first, then each parent up to (and including) the git
    root. Returns the first match found, stripping YAML frontmatter.

    Args:
        cwd: Current working directory path.

    Returns:
        Formatted content string, or empty string if not found.
    """
    import pathlib

    stop_at = _find_git_root(cwd)
    current = pathlib.Path(str(cwd)).resolve()

    for directory in [current, *current.parents]:
        dir_path = anyio.Path(str(directory))
        for name in (".hermes.md", "HERMES.md"):
            candidate = dir_path / name
            if await candidate.exists():
                try:
                    content = (await candidate.read_text(encoding="utf-8")).strip()
                    if content:
                        content = _strip_yaml_frontmatter(content)
                        threats = scan_for_threats(content, scope="context")
                        if threats:
                            return (
                                f"[BLOCKED: {name} contained potential prompt injection "
                                f"({', '.join(threats)}). Content not loaded.]"
                            )
                        result = f"## {name}\n\n{content}"
                        return _truncate_content(result, name)
                except Exception:
                    pass
        # Stop walking at the git root (inclusive)
        if stop_at is not None and str(directory) == str(stop_at):
            break
    return ""


async def _load_agents_md(cwd: anyio.Path) -> str:
    """Load AGENTS.md or agents.md from cwd.

    Args:
        cwd: Current working directory path.

    Returns:
        Formatted content string, or empty string if not found.
    """
    for name in ("AGENTS.md", "agents.md"):
        candidate = cwd / name
        if await candidate.exists():
            try:
                content = (await candidate.read_text(encoding="utf-8")).strip()
                if content:
                    threats = scan_for_threats(content, scope="context")
                    if threats:
                        return (
                            f"[BLOCKED: {name} contained potential prompt injection "
                            f"({', '.join(threats)}). Content not loaded.]"
                        )
                    result = f"## {name}\n\n{content}"
                    return _truncate_content(result, name)
            except Exception:
                pass
    return ""


async def _load_claude_md(cwd: anyio.Path) -> str:
    """Load CLAUDE.md or claude.md from cwd.

    Args:
        cwd: Current working directory path.

    Returns:
        Formatted content string, or empty string if not found.
    """
    for name in ("CLAUDE.md", "claude.md"):
        candidate = cwd / name
        if await candidate.exists():
            try:
                content = (await candidate.read_text(encoding="utf-8")).strip()
                if content:
                    threats = scan_for_threats(content, scope="context")
                    if threats:
                        return (
                            f"[BLOCKED: {name} contained potential prompt injection "
                            f"({', '.join(threats)}). Content not loaded.]"
                        )
                    result = f"## {name}\n\n{content}"
                    return _truncate_content(result, name)
            except Exception:
                pass
    return ""


async def _load_cursorrules(cwd: anyio.Path) -> str:
    """Load .cursorrules and/or .cursor/rules/*.mdc from cwd.

    Args:
        cwd: Current working directory path.

    Returns:
        Formatted content string, or empty string if not found.
    """
    cursorrules_content = ""

    cursorrules_file = cwd / ".cursorrules"
    if await cursorrules_file.exists():
        try:
            content = (await cursorrules_file.read_text(encoding="utf-8")).strip()
            if content:
                threats = scan_for_threats(content, scope="context")
                if threats:
                    cursorrules_content += (
                        f"[BLOCKED: .cursorrules contained potential prompt injection "
                        f"({', '.join(threats)}). Content not loaded.]\n\n"
                    )
                else:
                    cursorrules_content += f"## .cursorrules\n\n{content}\n\n"
        except Exception:
            pass

    cursor_rules_dir = cwd / ".cursor" / "rules"
    if await cursor_rules_dir.exists() and await cursor_rules_dir.is_dir():
        mdc_files: list[anyio.Path] = []
        async for f in cursor_rules_dir.iterdir():
            if str(f).endswith(".mdc"):
                mdc_files.append(f)
        for mdc_file in sorted(mdc_files, key=lambda p: str(p)):
            try:
                content = (await mdc_file.read_text(encoding="utf-8")).strip()
                if content:
                    threats = scan_for_threats(content, scope="context")
                    if threats:
                        cursorrules_content += (
                            f"[BLOCKED: .cursor/rules/{mdc_file.name} contained potential "
                            f"prompt injection ({', '.join(threats)}). Content not loaded.]\n\n"
                        )
                    else:
                        cursorrules_content += f"## .cursor/rules/{mdc_file.name}\n\n{content}\n\n"
            except Exception:
                pass

    if not cursorrules_content:
        return ""
    return _truncate_content(cursorrules_content.strip(), ".cursorrules")


async def _build_context(workspace_dir: anyio.Path | None = None) -> str:
    """Build the context tier by scanning for project context files.

    Scans workspace_dir if provided, otherwise falls back to cwd.
    Priority (first non-empty wins):
      1. .hermes.md / HERMES.md  (walks up to git root)
      2. AGENTS.md / agents.md   (directory only)
      3. CLAUDE.md / claude.md   (directory only)
      4. .cursorrules / .cursor/rules/*.mdc  (directory only)

    Args:
        workspace_dir: Workspace directory to scan. Falls back to cwd if None.

    Returns:
        Context tier string wrapped in '# Project Context' header,
        or empty string if no context files found.
    """
    search_dir = workspace_dir if workspace_dir is not None else anyio.Path(os.getcwd())

    project_context = (
        await _load_hermes_md(search_dir)
        or await _load_agents_md(search_dir)
        or await _load_claude_md(search_dir)
        or await _load_cursorrules(search_dir)
    )

    if not project_context:
        return ""

    return (
        "# Project Context\n\n"
        "The following project context files have been loaded and should be followed:\n\n"
        + project_context
    )


# ---------------------------------------------------------------------------
# Volatile tier
# ---------------------------------------------------------------------------


async def _load_memory_md(workspace_dir: anyio.Path) -> str:
    """Load workspace/memory.md if it exists.

    Args:
        workspace_dir: Path to the workspace root directory.

    Returns:
        Formatted memory section string, or empty string if not found.
    """
    memory_path = workspace_dir / "memory.md"
    if not await memory_path.exists():
        return ""
    try:
        content = (await memory_path.read_text(encoding="utf-8")).strip()
        if not content:
            return ""
        content = _truncate_content(content, "memory.md")
        return f"## Memory\n\n{content}"
    except Exception:
        return ""


async def _load_user_md() -> str:
    """Load ~/.hermes/USER.md if it exists.

    Returns:
        Formatted user profile section string, or empty string if not found.
    """
    user_path = anyio.Path(os.path.expanduser("~/.hermes/USER.md"))
    if not await user_path.exists():
        return ""
    try:
        content = (await user_path.read_text(encoding="utf-8")).strip()
        if not content:
            return ""
        content = _truncate_content(content, "USER.md")
        return f"## User Profile\n\n{content}"
    except Exception:
        return ""


async def _build_volatile(workspace_dir: anyio.Path, model: str | None = None) -> str:
    """Build the volatile tier with memory, user profile, date and optional model info.

    Memory and user profile are injected first; date/session/model/provider last.
    Uses date-only precision (not minute) to keep the date line byte-stable
    for the full day, maximizing prefix cache hits on the stable/context tiers.
    Session ID is read from PSI_SESSION_ID env var; provider from PSI_AI_PROVIDER.

    Args:
        workspace_dir: Path to the workspace root directory.
        model: Optional model name to include in the volatile block.

    Returns:
        Volatile tier string.
    """
    parts: list[str] = []

    # 1. Memory (workspace-local)
    memory = await _load_memory_md(workspace_dir)
    if memory:
        parts.append(memory)

    # 2. User profile (~/.hermes/USER.md)
    user_profile = await _load_user_md()
    if user_profile:
        parts.append(user_profile)

    # 3. Date + session_id + model + provider (date-only for prefix cache stability)
    now = datetime.now(tz=UTC)
    date_line = f"Conversation started: {now.strftime('%A, %B %d, %Y')}"
    session_id = os.environ.get("PSI_SESSION_ID")
    if session_id:
        date_line += f"\nSession ID: {session_id}"
    if model:
        date_line += f"\nModel: {model}"
    provider = os.environ.get("PSI_AI_PROVIDER")
    if provider:
        date_line += f"\nProvider: {provider}"
    parts.append(date_line)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def _estimate_tokens(message: dict[str, Any]) -> int:
    """Estimate token count for a message using chars/4 heuristic.

    Args:
        message: A conversation message with role and content.

    Returns:
        Estimated token count.
    """
    chars = 0
    content = message.get("content", "")
    if isinstance(content, str):
        chars = len(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    chars += len(block.get("text", ""))
                elif block.get("type") == "image":
                    chars += 4800  # ~1200 tokens estimate
    return max(1, chars // 4)


# ---------------------------------------------------------------------------
# System class
# ---------------------------------------------------------------------------


class System:
    """Hermes-style workspace system configuration.

    Implements three-tier system prompt assembly:
    - stable: identity, guidance, skills index, environment hints
    - context: project context files from cwd
    - volatile: current date, model name
    """

    def __init__(self, workspace_dir: anyio.Path) -> None:
        """Initialize the System instance.

        Args:
            workspace_dir: Path to the workspace directory.
        """
        self._workspace_dir = workspace_dir

    async def build_system_prompt(self, model: str | None = None) -> str:
        """Build the three-tier system prompt.

        Args:
            model: Optional model name for conditional tool-use enforcement
                   guidance and volatile tier model line.

        Returns:
            Complete system prompt string with all non-empty tiers joined by
            double newlines.
        """
        stable = await _build_stable(self._workspace_dir, model=model)
        context = await _build_context(workspace_dir=self._workspace_dir)
        volatile = await _build_volatile(self._workspace_dir, model=model)

        return "\n\n".join(p for p in (stable, context, volatile) if p)

    async def compact_history(
        self,
        history: list[dict[str, Any]],
        complete_fn: CompleteFn,
        max_tokens: int = 4000,
        keep_recent_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Compact conversation history using LLM summarisation.

        When total token count exceeds max_tokens, calls complete_fn to
        summarise older messages, then prepends the summary as a system
        message. Falls back to simple truncation if complete_fn fails.

        Args:
            history: List of conversation messages with role and content.
            complete_fn: Async function for single-turn LLM conversation.
            max_tokens: Maximum tokens to keep in history.
            keep_recent_tokens: Tokens of recent messages to preserve verbatim.
                Defaults to max_tokens // 2.

        Returns:
            Compacted history list.
        """
        total_tokens = sum(_estimate_tokens(msg) for msg in history)
        if total_tokens <= max_tokens:
            return history

        keep_budget = keep_recent_tokens or (max_tokens // 2)

        # Walk backwards to find the cut point for recent messages
        accumulated = 0
        cut_index = len(history)
        for i in range(len(history) - 1, -1, -1):
            accumulated += _estimate_tokens(history[i])
            if accumulated >= keep_budget:
                cut_index = i + 1
                break
        else:
            cut_index = 0

        recent = history[cut_index:]
        older = history[:cut_index]

        if not older:
            return recent

        # Try LLM summarisation
        try:

            def _msg_text(m: dict[str, Any]) -> str:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                text = content if isinstance(content, str) else "[non-text content]"
                return f"{role}: {text}"

            older_text = "\n".join(_msg_text(m) for m in older)
            summary_prompt = [
                {
                    "role": "user",
                    "content": (
                        "Please summarise the following conversation history concisely, "
                        "preserving all key facts, decisions, and context:\n\n" + older_text
                    ),
                }
            ]
            summary = await complete_fn(summary_prompt)
            summary_message: dict[str, Any] = {
                "role": "system",
                "content": f"[Summary of earlier conversation]\n{summary}",
            }
            return [summary_message, *recent]
        except Exception:
            # Fallback: simple truncation
            return recent
