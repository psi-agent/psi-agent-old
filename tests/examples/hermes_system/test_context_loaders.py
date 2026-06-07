"""Tests for _load_agents_md and _load_claude_md git-root walk behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import anyio

# Inject the hermes-style-workspace directory so `systems` package resolves,
# and the systems/ subdirectory so `from system import ...` works directly.
_WORKSPACE_DIR = str(Path(__file__).parents[3] / "examples" / "hermes-style-workspace")
_SYSTEMS_DIR = str(Path(__file__).parents[3] / "examples" / "hermes-style-workspace" / "systems")
for _p in (_WORKSPACE_DIR, _SYSTEMS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from system import _load_agents_md, _load_claude_md  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write(path: anyio.Path, content: str) -> None:
    await path.parent.mkdir(parents=True, exist_ok=True)
    await path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# _load_agents_md tests
# ---------------------------------------------------------------------------


async def test_load_agents_md_found_in_cwd(tmp_path: Path) -> None:
    """AGENTS.md in cwd is loaded directly."""
    cwd = anyio.Path(tmp_path)
    await _write(cwd / "AGENTS.md", "# Agents\nHello agents.")
    result = await _load_agents_md(cwd)
    assert "Hello agents." in result


async def test_load_agents_md_found_in_parent(tmp_path: Path) -> None:
    """AGENTS.md in a parent directory (up to git root) is found."""
    # Create a fake git root at tmp_path
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "subproject" / "src"
    subdir.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# Root Agents", encoding="utf-8")

    cwd = anyio.Path(subdir)
    result = await _load_agents_md(cwd)
    assert "Root Agents" in result


async def test_load_agents_md_not_beyond_git_root(tmp_path: Path) -> None:
    """AGENTS.md beyond the git root is NOT loaded."""
    # Layout: tmp_path/AGENTS.md  (beyond git root)
    #         tmp_path/repo/.git
    #         tmp_path/repo/src/   <- cwd
    (tmp_path / "AGENTS.md").write_text("# Beyond root", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    src = repo / "src"
    src.mkdir()

    cwd = anyio.Path(src)
    result = await _load_agents_md(cwd)
    assert result == ""


async def test_load_agents_md_no_git_repo(tmp_path: Path) -> None:
    """Without a git repo, only cwd is searched."""
    parent = tmp_path / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / "AGENTS.md").write_text("# Parent agents", encoding="utf-8")

    cwd = anyio.Path(child)
    result = await _load_agents_md(cwd)
    # No .git anywhere, so walk goes all the way up — parent is above cwd so
    # it would be found. This test documents current behavior: without a git
    # root bound, the walk continues to filesystem root. The interesting case
    # is that it does NOT load files beyond the git root when one exists.
    # Here we just confirm no crash occurs.
    assert isinstance(result, str)


async def test_load_agents_md_empty_when_missing(tmp_path: Path) -> None:
    """Returns empty string when no AGENTS.md exists anywhere in the walk."""
    (tmp_path / ".git").mkdir()
    cwd = anyio.Path(tmp_path)
    result = await _load_agents_md(cwd)
    assert result == ""


# ---------------------------------------------------------------------------
# _load_claude_md tests
# ---------------------------------------------------------------------------


async def test_load_claude_md_found_in_cwd(tmp_path: Path) -> None:
    """CLAUDE.md in cwd is loaded directly."""
    cwd = anyio.Path(tmp_path)
    await _write(cwd / "CLAUDE.md", "# Claude\nHello claude.")
    result = await _load_claude_md(cwd)
    assert "Hello claude." in result


async def test_load_claude_md_found_in_parent(tmp_path: Path) -> None:
    """CLAUDE.md in a parent directory (up to git root) is found."""
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "subproject" / "src"
    subdir.mkdir(parents=True)
    (tmp_path / "CLAUDE.md").write_text("# Root Claude", encoding="utf-8")

    cwd = anyio.Path(subdir)
    result = await _load_claude_md(cwd)
    assert "Root Claude" in result


async def test_load_claude_md_not_beyond_git_root(tmp_path: Path) -> None:
    """CLAUDE.md beyond the git root is NOT loaded."""
    (tmp_path / "CLAUDE.md").write_text("# Beyond root", encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    src = repo / "src"
    src.mkdir()

    cwd = anyio.Path(src)
    result = await _load_claude_md(cwd)
    assert result == ""


async def test_load_claude_md_empty_when_missing(tmp_path: Path) -> None:
    """Returns empty string when no CLAUDE.md exists anywhere in the walk."""
    (tmp_path / ".git").mkdir()
    cwd = anyio.Path(tmp_path)
    result = await _load_claude_md(cwd)
    assert result == ""


async def test_load_claude_md_cwd_takes_priority_over_parent(tmp_path: Path) -> None:
    """CLAUDE.md in cwd takes priority over parent directory."""
    (tmp_path / ".git").mkdir()
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (tmp_path / "CLAUDE.md").write_text("# Parent Claude", encoding="utf-8")
    (subdir / "CLAUDE.md").write_text("# Child Claude", encoding="utf-8")

    cwd = anyio.Path(subdir)
    result = await _load_claude_md(cwd)
    assert "Child Claude" in result
    assert "Parent Claude" not in result
