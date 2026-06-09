---
name: python-static-analysis
description: Static analysis and type checking for Python
category: coding
created_by: agent
created_at: 2026-02-10T00:00:00Z
updated_at: 2026-06-09T15:21:01Z
---

Use this skill when improving Python code quality with static analysis, linting, formatting, and type checking.

Scope
- Explain how to combine formatting, linting, and type checking in a practical workflow.
- Prefer current, widely used tools and concise recommendations.
- Absorb basic guidance about Python type hints rather than duplicating it in a separate skill.

Recommended toolchain
- Formatter: `black`
- Import sorter: `isort`
- Linter: `ruff`
- Type checker: `mypy` or `pyright`
- Optional security scan: `bandit`

Core guidance
1. Start with formatting and linting
   - Run `black .`
   - Run `isort .`
   - Run `ruff check . --fix`
2. Add type checking
   - For libraries and larger apps, recommend type annotations on public APIs first.
   - Use `mypy .` or `pyright` for project-wide checks.
   - Encourage gradual adoption; avoid demanding full annotation coverage immediately.
3. Focus on high-value types
   - Function params and returns
   - Dataclass/model fields
   - Collection element types
   - `TypedDict`, `Protocol`, `Literal`, and generics where they improve clarity
4. Handle missing or dynamic typing pragmatically
   - Use library stubs when available
   - Isolate dynamic code behind typed interfaces
   - Prefer narrow `cast()` or targeted ignores over broad suppression
5. Keep CI fast and actionable
   - Run formatter/linter/type checker in CI
   - Fail on new issues, not necessarily all historic issues during migration
   - Use pre-commit hooks when helpful

Minimal examples
- Typed function:
python
  def slugify(title: str) -> str:
      return title.lower().replace(" ", "-")

- Typed optional:
python
  from typing import Optional

  def find_user(user_id: int) -> Optional[dict[str, str]]:
      ...

- Typed protocol:
python
  from typing import Protocol

  class SupportsClose(Protocol):
      def close(self) -> None: ...


Suggested config snippets
- `pyproject.toml`:
toml
  [tool.black]
  line-length = 88

  [tool.isort]
  profile = "black"

  [tool.ruff]
  line-length = 88

  [tool.mypy]
  python_version = "3.11"
  warn_unused_ignores = true
  disallow_untyped_defs = false
  no_implicit_optional = true


When responding
- If the user asks for setup, provide install commands, config, and CI examples.
- If the user asks about errors, explain the specific lint/type message and show the smallest safe fix.
- If the user asks whether to use mypy or pyright, recommend either based on team preference and existing ecosystem, not ideology.
- Keep advice practical and incremental.