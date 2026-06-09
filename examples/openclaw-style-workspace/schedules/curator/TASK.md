---
name: curator
cron: "0 */168 * * *"
description: 扫描 agent-created skills 并执行质量维护
---

## 触发条件

本任务每 168 小时（7 天）触发一次，但实际执行还需满足以下条件：

1. **距上次运行 ≥ 168 小时**：通过 `.curator_state.json` 中的 `last_run_at` 判断
2. **系统空闲 ≥ 2 小时**：`idle_for_seconds >= 7200`，避免在活跃会话中打扰用户

当两个条件同时满足时，`maybe_run_curator()` 才会执行完整的 curator 流程。

## 调用方式

psi-session 在处理此定时任务时，调用：

```python
from curator import maybe_run_curator

await maybe_run_curator(
    workspace_dir=workspace_dir,
    complete_fn=complete_fn,
    idle_for_seconds=idle_seconds,
)
```

## 执行内容

1. 扫描 `skills/` 目录，收集所有 `created_by: agent` 的 skill
2. 根据 `created_at` / `updated_at` 计算时效标签（active / stale / archive-candidate）
3. 调用 LLM 对每个 skill 进行语义审查，输出 keep / patch / merge / archive 决策
4. 执行决策：patch 更新内容，merge 合并相似 skill，archive 归档过时 skill
5. 写入 `.curator_report.md` 和更新 `.curator_state.json`

只有 `created_by: agent` 的 skill 会被处理，用户手写的 skill 不受影响。
