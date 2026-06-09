---
name: user-language-and-timezone-preferences
description: Persisted user preferences for language and timezone handling
category: preferences
created_by: agent
created_at: 2026-06-09T15:15:28Z
---

---
name: user-language-and-timezone-preferences
description: Persisted user preferences for language and timezone handling
category: preferences
created_by: agent
created_at: 2026-06-09T00:00:00Z
---

# User language and timezone preferences

## Language preference
- If the user writes in Chinese, respond in Chinese.
- Match the user's language choice within the session unless they ask to switch.

## Timezone preference
- Treat the user's default timezone as UTC+8 / China time when timezone context matters.
- If dates, schedules, deadlines, cron timing, logs, or timestamps are discussed without another timezone specified, default to UTC+8.

## Application
- Apply these preferences implicitly; do not repeatedly restate them unless relevant.
- If a task depends on timezone-sensitive interpretation, use UTC+8 as the default assumption and mention it briefly when helpful.
