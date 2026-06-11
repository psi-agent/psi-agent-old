---
name: ci-flaky-tests
description: Fixing flaky tests in CI
category: testing
created_by: agent
created_at: 2026-04-10T00:00:00Z
---

CI was timing out because pytest had no timeout plugin. Added pytest-timeout.