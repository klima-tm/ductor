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
pass that time to the schedule tool. Inspect every simultaneous event returned,
but treat overlaps as raw evidence rather than proof that every nominal block
will happen independently. Reconstruct the most likely real schedule by
distinguishing concrete commitments, deliberate flexible tasks, and background
routine templates; resolve likely overrides and mention meaningful transitions
or gaps instead of mechanically narrating every row.
Calendar titles and metadata are raw source data, not necessarily natural
dialogue. Rewrite obvious imported labels or explanatory suffixes naturally
without changing the fact: for example, render a teacher stored as
`Jerel with a J` simply as `Jerel`. Do not simplify uncertain wording.

Use event specificity, recurrence, origin, timing, and known habits to infer the
likely resolution. Egor usually reconciles that day's conflicts during the
morning. Other recurring blocks normally happen at their default times, but he
reflows them when a booked lesson lands elsewhere. `Lesson` is the movable
default slot for a real lesson; a concrete italki booking normally represents
that day's actual lesson rather than an additional lesson merely because the
template remains on the calendar. An overlap makes that override especially
clear, but use the whole context rather than one rigid matching rule.

`Post something` is a real recurring Tuesday/Thursday task with a default time,
not an occasional event, but it is flexible. When it conflicts with a fixed
appointment, it will probably be moved earlier or later during that morning's
reconciliation. Apply the broader principle to similar events instead of
hard-coding an answer around these titles. Explain the probable real sequence,
not just the existence of conflicts, and keep all such resolutions as natural
low-stakes inferences rather than guarantees.
