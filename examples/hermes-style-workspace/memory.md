# Memory

This file stores persistent memory across conversations.
The agent reads this on every turn and injects it into the system prompt.

## Example entries

- User prefers Python over JavaScript for automation tasks
- Project uses uv for dependency management
- Database: PostgreSQL, connection string in .env
- Deployment: Docker on Linux VPS

---

**Usage:** Place this file at `workspace/memory.md`. Edit it directly or
have the agent update it via a bash tool call. Content is injected into
the volatile tier of the system prompt on every conversation.
