# Approved shared context tools

Use these tools only to answer questions about the administrator's explicitly
approved shared information.

Claude commands:

- `python3 tools/context_tools/context.py current-work`
- `python3 tools/context_tools/context.py goals`
- `python3 tools/context_tools/context.py schedule --start YYYY-MM-DD --end YYYY-MM-DD`
- `python3 tools/context_tools/context.py diet`
- `python3 tools/context_tools/context.py search QUERY`

Codex receives equivalent read-only MCP tools named `get_current_work`,
`get_goals`, `get_schedule`, `get_diet`, and `search_shared_context`.

Always inspect `available`, `updated_at`, and `stale`. State missing or stale
information honestly. Do not inspect other files or infer denied categories.

For a specific date, trust Calendar events over a routine's `Default time`.
Routine times and windows describe the normal structure only. The schedule tool
already removes restricted routine rows; never speculate about omitted data.
