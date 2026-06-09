---
name: python-aiohttp-client-patterns
description: Robust aiohttp client patterns for pooling, retries, and connectivity debugging
category: coding
created_by: agent
created_at: 2026-06-09T15:15:28Z
updated_at: 2026-06-09T15:20:53Z
---

---
name: python-aiohttp-client-patterns
description: Robust aiohttp client patterns for pooling, retries, and connectivity debugging
category: coding
created_by: agent
created_at: 2026-06-09T15:15:28Z
---

# aiohttp client patterns

## Debugging `ClientConnectorError`
When `aiohttp.ClientConnectorError: Cannot connect to host` appears:
- Verify the server is actually running.
- Confirm host and port are correct.
- Check DNS, firewall, and network reachability.
- Reproduce with `curl` against the same endpoint.
- Log the full exception traceback.
- If TLS negotiation is suspected, test with `aiohttp.TCPConnector(ssl=False)` in a controlled debugging scenario.

## Under-load intermittent failures
If connections fail intermittently under load:
- Suspect connection pool exhaustion or poor session lifecycle management.
- Reuse a single `aiohttp.ClientSession` per process or application scope.
- Do not create a new `ClientSession` per request.
- Tune the connector explicitly, e.g. `aiohttp.TCPConnector(limit=50, limit_per_host=20)`.

## Retries
- Add retries with exponential backoff for transient connection failures.
- A canonical `tenacity` pattern is:
  - `@retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))`
- Log each retry attempt at WARNING level.
- Use retries only for operations that are safe to retry or are designed to be idempotent.

## Refactor guidance
When refactoring an HTTP client module:
- Centralize session and connector ownership.
- Encapsulate request behavior in a typed client class.
- Update call sites to use the shared client abstraction rather than raw per-call session creation.
- If type-check validation is mentioned for this user, prefer `ty check` rather than `mypy`.
