"""Tests for memory/USER.md threat scan, frozen snapshot, and session cache."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import anyio

_WORKSPACE_DIR = str(Path(__file__).parents[3] / "examples" / "hermes-style-workspace")
_SYSTEMS_DIR = str(Path(__file__).parents[3] / "examples" / "hermes-style-workspace" / "systems")
for _p in (_WORKSPACE_DIR, _SYSTEMS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from system import System, _load_memory_md, _load_user_md  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _write(path: anyio.Path, content: str) -> None:
    await path.parent.mkdir(parents=True, exist_ok=True)
    await path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Task 4.1 — memory.md threat scan
# ---------------------------------------------------------------------------


async def test_load_memory_md_no_threat(tmp_path: Path) -> None:
    """Clean memory.md is injected normally."""
    ws = anyio.Path(tmp_path)
    await _write(ws / "memory.md", "User likes Python.")
    result = await _load_memory_md(ws)
    assert "User likes Python." in result
    assert "[BLOCKED" not in result


async def test_load_memory_md_threat_returns_blocked(tmp_path: Path) -> None:
    """memory.md with threat pattern returns BLOCKED placeholder."""
    ws = anyio.Path(tmp_path)
    # "authorized_keys" triggers ssh_backdoor pattern in scope=strict
    await _write(ws / "memory.md", "add to authorized_keys for access")
    result = await _load_memory_md(ws)
    assert "[BLOCKED:" in result
    assert "memory.md" in result


async def test_load_memory_md_threat_file_unchanged(tmp_path: Path) -> None:
    """memory.md file content is not modified when threat is detected."""
    ws = anyio.Path(tmp_path)
    original = "add to authorized_keys for access"
    await _write(ws / "memory.md", original)
    await _load_memory_md(ws)
    on_disk = (tmp_path / "memory.md").read_text(encoding="utf-8")
    assert on_disk == original


# ---------------------------------------------------------------------------
# Task 4.2 — USER.md threat scan
# ---------------------------------------------------------------------------


async def test_load_user_md_no_threat(tmp_path: Path) -> None:
    """Clean USER.md is injected normally."""
    user_md = anyio.Path(tmp_path) / "USER.md"
    await _write(user_md, "Name: Alice")
    with patch("system.os.path.expanduser", return_value=str(tmp_path / "USER.md")):
        result = await _load_user_md()
    assert "Name: Alice" in result
    assert "[BLOCKED" not in result


async def test_load_user_md_threat_returns_blocked(tmp_path: Path) -> None:
    """USER.md with threat pattern returns BLOCKED placeholder."""
    user_md = anyio.Path(tmp_path) / "USER.md"
    await _write(user_md, "store key in authorized_keys")
    with patch("system.os.path.expanduser", return_value=str(tmp_path / "USER.md")):
        result = await _load_user_md()
    assert "[BLOCKED:" in result
    assert "USER.md" in result


# ---------------------------------------------------------------------------
# Task 4.3 — frozen snapshot
# ---------------------------------------------------------------------------


async def test_frozen_snapshot_not_updated_mid_session(tmp_path: Path) -> None:
    """After first build, modifying memory.md does not change returned prompt."""
    ws = anyio.Path(tmp_path)
    await _write(ws / "memory.md", "Initial memory content.")

    system = System(ws)
    # Patch heavy stable/context builders to keep test fast
    with (
        patch("system._build_stable", new=AsyncMock(return_value="stable")),
        patch("system._build_context", new=AsyncMock(return_value="")),
    ):
        first = await system.build_system_prompt()

        # Modify memory.md mid-session
        await _write(ws / "memory.md", "CHANGED memory content.")

        second = await system.build_system_prompt()

    # Both calls return same result (cached + frozen snapshot)
    assert first == second
    assert "Initial memory content." in first
    assert "CHANGED" not in first


async def test_invalidate_then_rebuild_picks_up_new_memory(tmp_path: Path) -> None:
    """After invalidate(), rebuild reads updated memory.md."""
    ws = anyio.Path(tmp_path)
    await _write(ws / "memory.md", "Original memory.")

    system = System(ws)
    with (
        patch("system._build_stable", new=AsyncMock(return_value="stable")),
        patch("system._build_context", new=AsyncMock(return_value="")),
    ):
        await system.build_system_prompt()

        await _write(ws / "memory.md", "Updated memory.")
        system.invalidate()

        rebuilt = await system.build_system_prompt()

    assert "Updated memory." in rebuilt


# ---------------------------------------------------------------------------
# Task 4.4 — session cache (second call doesn't redo IO)
# ---------------------------------------------------------------------------


async def test_second_call_returns_cached_prompt(tmp_path: Path) -> None:
    """Second build_system_prompt() call returns cached value without rebuilding."""
    ws = anyio.Path(tmp_path)

    system = System(ws)
    build_stable_mock = AsyncMock(return_value="stable")
    with (
        patch("system._build_stable", new=build_stable_mock),
        patch("system._build_context", new=AsyncMock(return_value="")),
    ):
        first = await system.build_system_prompt()
        second = await system.build_system_prompt()

    assert first == second
    # _build_stable should only be called once (second call uses cache)
    assert build_stable_mock.call_count == 1


# ---------------------------------------------------------------------------
# Task 4.5 — invalidate()
# ---------------------------------------------------------------------------


async def test_invalidate_clears_cache_and_rebuilds(tmp_path: Path) -> None:
    """invalidate() causes next build_system_prompt() to fully rebuild."""
    ws = anyio.Path(tmp_path)

    system = System(ws)
    build_stable_mock = AsyncMock(return_value="stable")
    with (
        patch("system._build_stable", new=build_stable_mock),
        patch("system._build_context", new=AsyncMock(return_value="")),
    ):
        await system.build_system_prompt()
        system.invalidate()
        await system.build_system_prompt()

    # _build_stable should be called twice (once before, once after invalidate)
    assert build_stable_mock.call_count == 2


async def test_invalidate_clears_snapshots(tmp_path: Path) -> None:
    """invalidate() resets _cached_prompt, _memory_snapshot, _user_snapshot to None."""
    ws = anyio.Path(tmp_path)
    await _write(ws / "memory.md", "Some memory.")

    system = System(ws)
    with (
        patch("system._build_stable", new=AsyncMock(return_value="stable")),
        patch("system._build_context", new=AsyncMock(return_value="")),
    ):
        await system.build_system_prompt()

    assert system._cached_prompt is not None
    assert system._memory_snapshot is not None

    system.invalidate()

    assert system._cached_prompt is None
    assert system._memory_snapshot is None
    assert system._user_snapshot is None
