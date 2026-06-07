"""Skill management tool — create, update, or delete skills in workspace/skills/."""

from __future__ import annotations

import contextlib

import anyio


async def tool(
    action: str,
    name: str,
    description: str = "",
    content: str = "",
) -> str:
    """Manage skills stored under workspace/skills/.

    Args:
        action: One of ``"create"``, ``"patch"``, or ``"delete"``.
        name: Skill directory name (kebab-case, e.g. ``"my-skill"``).
        description: Short description for the SKILL.md frontmatter
            (used on create and patch).
        content: Body text for the SKILL.md file (used on create and patch).

    Returns:
        Confirmation message describing what was done.
    """
    skill_dir = anyio.Path("skills") / name
    skill_md = skill_dir / "SKILL.md"

    if action == "create":
        await skill_dir.mkdir(parents=True, exist_ok=True)
        frontmatter = f"---\nname: {name}\ndescription: {description}\n---\n\n"
        await skill_md.write_text(frontmatter + content, encoding="utf-8")
        return f"Skill '{name}' created at {skill_md}."

    if action == "patch":
        if not await skill_md.exists():
            return f"Skill '{name}' does not exist. Use action='create' to create it."
        existing = await skill_md.read_text(encoding="utf-8")
        # Replace body while preserving frontmatter if content provided
        if content:
            if existing.startswith("---"):
                end = existing.find("\n---", 3)
                if end != -1:
                    header = existing[: end + 4]
                    await skill_md.write_text(header + "\n\n" + content, encoding="utf-8")
                else:
                    await skill_md.write_text(existing + "\n\n" + content, encoding="utf-8")
            else:
                await skill_md.write_text(content, encoding="utf-8")
        return f"Skill '{name}' patched."

    if action == "delete":
        if not await skill_md.exists():
            return f"Skill '{name}' does not exist."
        await skill_md.unlink()
        # Remove directory if empty
        with contextlib.suppress(OSError):
            await skill_dir.rmdir()
        return f"Skill '{name}' deleted."

    return f"Unknown action: {action!r}. Use 'create', 'patch', or 'delete'."
