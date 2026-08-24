# Approved shared context tools

Use these tools only to answer questions about the administrator's explicitly
approved shared information.

Claude commands:

- `python3 tools/context_tools/context.py current-work`
- `python3 tools/context_tools/context.py goals`
- `python3 tools/context_tools/context.py schedule --start YYYY-MM-DD --end YYYY-MM-DD`
- For a clock-time question: `python3 tools/context_tools/context.py schedule --start YYYY-MM-DD --end YYYY-MM-DD --at HH:MM`
- `python3 tools/context_tools/context.py diet`
- `python3 tools/context_tools/context.py search QUERY`

Codex receives equivalent read-only MCP tools named `get_current_work`,
`get_goals`, `get_schedule`, `get_diet`, and `search_shared_context`.

Always inspect `available`, `updated_at`, and `stale`. State missing or stale
information honestly. Do not inspect other files or infer denied categories.

For a specific date, trust Calendar events over a routine's `Default time`.
Routine times and windows describe the normal structure only. The schedule tool
already removes restricted routine rows; never speculate about omitted data.

Interpret clock times only through `display_start` and `display_end` in the
returned schedule timezone. When the user asks what happens at a specific time,
pass that time to the schedule tool. Calendar overlaps are intentional: report
every returned simultaneous event, foregrounding a specific booked appointment
or class over a broad routine block without hiding the conflicting blocks.
Interpret the likely practical resolution using event semantics and known
habits, never hard-coded event titles. Egor usually reconciles same-day schedule
conflicts during the morning of the day they occur, so it can be reasonable to
say that a flexible event will probably be rescheduled later when it overlaps a
fixed class or appointment. Treat this as a soft inference, not a guarantee, and
phrase it naturally rather than repeating a fixed sentence.
