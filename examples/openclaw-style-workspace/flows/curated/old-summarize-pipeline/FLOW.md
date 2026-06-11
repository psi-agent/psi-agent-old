---
name: old-summarize-pipeline
description: Summarise documents using a single LLM session
category: research
created_by: agent
created_at: 2026-01-10T00:00:00Z
---

A simple one-shot summarisation pipeline. Now superseded by parallel approaches.

```typescript
import { flow } from "@agent-flow/core";
const summary = await flow.session({ prompt: "Summarize: {{text}}" });
```
