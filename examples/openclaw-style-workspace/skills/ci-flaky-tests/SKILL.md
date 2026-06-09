---
name: ci-flaky-tests
description: Fixing flaky tests in CI
category: testing
created_by: agent
created_at: 2026-04-10T00:00:00Z
updated_at: 2026-06-09T15:21:01Z
---

Use this skill when diagnosing or reducing flaky tests in CI.

Goal
- Help identify whether failures come from timing, ordering, shared state, environment differences, networking, or test data.

Triage workflow
1. Confirm flakiness
   - Check whether the same commit passes on rerun.
   - Record failure rate, affected test names, and CI job/environment.
2. Reproduce locally
   - Run the test repeatedly.
   - Randomize order if the framework supports it.
   - Match CI settings: Python version, OS, env vars, parallelism, containers, and services.
3. Classify the cause
   - Timing/race conditions
   - Order dependence/shared mutable state
   - External dependency/network instability
   - Clock/timezone/date assumptions
   - Resource leakage: files, sockets, DB rows, temp dirs
   - Parallel test interference
4. Apply the smallest reliable fix
   - Replace arbitrary sleeps with explicit polling or event synchronization.
   - Isolate state with fresh fixtures and cleanup.
   - Mock external services when possible.
   - Freeze time or set timezone explicitly.
   - Use unique resource names per test.
   - Ensure retries are used only for diagnosis, not as the final fix.
5. Prevent recurrence
   - Add regression coverage for the discovered failure mode.
   - Keep tests deterministic and hermetic.
   - Monitor flaky-test frequency in CI.

Common fixes
- Timing issues: wait on a condition, not `sleep()`.
- Async issues: ensure all tasks are awaited/cancelled and event loops are not reused incorrectly.
- DB issues: wrap tests in transactions or reset state between tests.
- Order dependence: avoid module/global mutation; use per-test setup.
- Network issues: stub HTTP calls; if integration is required, add health checks and generous but bounded timeouts.

What to include in responses
- A short hypothesis list ranked by likelihood.
- Concrete reproduction commands.
- Suggested instrumentation: extra logging, timestamps, random seed capture, thread/task dumps.
- A recommended durable fix, plus a temporary quarantine only if necessary.

Avoid
- Suggesting blanket retries as the solution.
- Assuming CI infrastructure is the cause without evidence.
- Proposing broad sleeps or disabling assertions.