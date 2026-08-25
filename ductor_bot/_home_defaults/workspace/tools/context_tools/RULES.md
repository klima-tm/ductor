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
Ordinary calls are compact by default: each Calendar event includes the matched
approved Routine evidence, while full Routine bodies and provider metadata stay
hidden. Request `--with-routines`/`include_routines=true`, a `routine_query`, or
`--full-event-metadata`/`include_event_metadata=true` only when those details are
actually needed.
Likely replaced recurring templates are excluded from ordinary
`calendar_events`. If the user explicitly asks why raw Calendar entries look
duplicated, rerun with `--include-replaced-templates` or
`include_replaced_templates=true`; do not enable it for normal availability.

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

Use current event specificity, recurrence, origin, timing, approved Routines
evidence, and known habits to infer the likely resolution. Treat
`schedule_evidence` as internal reasoning material, not language to expose.
Never mention calendar plumbing, IDs, URLs, recurrence flags, or database
classification in an ordinary availability answer. Egor usually
reconciles that day's conflicts during the morning, so future overlaps may still
move. A concrete booked or imported event is normally stronger evidence than an
overlapping background routine template, while a scheduled but flexible task
may move around a fixed commitment. Reconstruct the probable real sequence and
meaningful gaps from the current data rather than encoding named event titles or
recurrence patterns as response rules. Do not surface recurrence, classification,
or other internal metadata unless it actually helps answer the user's question.
Keep the resolution as a natural low-stakes inference rather than a guarantee.
When `same_activity_groups` links multiple events to the same Routine schedule
block, treat them as possible alternative instances of one activity rather than
automatically adding them together. A one-off non-primary event is stronger
evidence of the concrete instance than a recurring primary-calendar template;
when `likely_schedule_roles` marks that relationship, resolve it before the
first reply and exclude the replaced template as an independent commitment by
default. Only count both when surrounding data clearly supports genuinely
separate occurrences.

Answer the user's real social decision, not the calendar database. Lead with the
direct availability conclusion, then include only the events or likely changes
that affect the practical recommendation. Do not dump the rest of the day merely
because it was returned. When a concrete event appears to displace a routine
template, treat the downstream template sequence as provisional rather than
using it to claim exact availability with certainty. A calendar that still shows
those overlaps may simply not reflect Egor's morning reconciliation yet. State
the likely real sequence naturally; do not explain it as a technical proof.
When `schedule_reflow.unresolved` is true, its recurring candidates lost their
original slots to a concrete event and may be moved elsewhere. Do not call the
period immediately after the concrete event definitely free; describe the
likely reflow and recommend only a genuinely reliable window or a direct message.
