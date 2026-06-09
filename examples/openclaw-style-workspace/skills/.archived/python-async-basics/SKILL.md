---
name: python-async-basics
description: Python asyncio fundamentals
category: coding
created_by: agent
created_at: 2026-03-01T00:00:00Z
updated_at: 2026-06-09T15:20:53Z
---

---
name: python-async-basics
description: Python asyncio fundamentals
category: coding
created_by: agent
created_at: 2026-03-01T00:00:00Z
---

# Python asyncio fundamentals

## Core rules
- Use `async` / `await` correctly.
- Always await coroutines unless you intentionally schedule them as background tasks.
- Never block the event loop with synchronous long-running work.

## Running tasks concurrently
- Use `asyncio.gather()` to run multiple independent coroutines concurrently and await their combined completion.
- Example pattern: `await asyncio.gather(task_a(), task_b())`.
- If you want to collect failures instead of failing fast, use `return_exceptions=True`.

## `create_task()` vs `gather()`
- `asyncio.create_task()` schedules a coroutine immediately and returns a `Task` object.
- Use `create_task()` when you need to start work now and await it later, manage task lifetime explicitly, or cancel tasks individually.
- `asyncio.gather()` is a coordination primitive that awaits multiple coroutines or tasks together and returns their results in order.
- Use `gather()` when you want structured waiting on a known group of concurrent operations.

## Timeouts
- To apply a timeout to one operation, use `await asyncio.wait_for(coro(), timeout=5.0)`.
- This raises `asyncio.TimeoutError` when the timeout expires.
- For grouped or scoped timeout handling in Python 3.11+, prefer `asyncio.timeout()` as a context manager.
