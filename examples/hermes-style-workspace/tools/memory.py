"""Persistent memory tool — read and write workspace/memory.md."""

from __future__ import annotations

import anyio


async def tool(action: str = "read", content: str = "") -> str:
    """Read or write persistent memory stored in workspace/memory.md.

    Args:
        action: Either ``"read"`` to retrieve memory contents or
            ``"write"`` to overwrite the entire memory file with new content.
        content: New memory content to write (only used when action="write").

    Returns:
        Current memory contents on read, or a confirmation message on write.
    """
    memory_path = anyio.Path("memory.md")
    # memory_path = anyio.Path("/data6/sby/psi-agent-old/examples/hermes-style-workspace/memory.md")

    if action == "read":
        if not await memory_path.exists():
            return "(memory is empty)"
        text = (await memory_path.read_text(encoding="utf-8")).strip()
        return text if text else "(memory is empty)"

    if action == "write":
        await memory_path.write_text(content, encoding="utf-8")
        return "Memory saved."

    return f"Unknown action: {action!r}. Use 'read' or 'write'."
