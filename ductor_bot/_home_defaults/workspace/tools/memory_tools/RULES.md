# Durable Memory Tools

Use `memory.py` proactively during the current conversation. When you identify
a stable personal fact, preference, relationship, important context, plan, or
correction that should survive future sessions, you must call this tool before
replying.

The tool is scoped by an ephemeral capability to the current chat profile.
It cannot select or inspect another user.

If native `memory_add`, `memory_search`, `memory_update`, `memory_supersede`,
and `memory_forget` tools are available, use them directly. Otherwise use the
Python commands below.

## Operations

```bash
python3 tools/memory_tools/memory.py add --category preference "The user prefers concise answers"
python3 tools/memory_tools/memory.py search "concise answers"
python3 tools/memory_tools/memory.py update MEMORY_ID "Corrected fact"
python3 tools/memory_tools/memory.py supersede MEMORY_ID "Replacement fact"
python3 tools/memory_tools/memory.py forget MEMORY_ID
```

- Use `add` for a new durable fact.
- Use `search` before changing or forgetting an existing fact.
- Use `update` for a correction that does not need historical preservation.
- Use `supersede` when a previously true fact changed; this preserves the old
  fact as historical and creates an active replacement.
- Use `forget` only when the user explicitly asks for deletion.
- Never store credentials, secrets, speculative interpretations, or temporary
  conversational details.
- Do not claim that memory succeeded unless the tool returns `success: true`.
