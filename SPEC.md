# Skill format — version 1

A skill is a JSON document. Any implementation that follows this page can replay a skill learned by another.

```json
{
  "format": 1,
  "intent": "create_note_for_record",
  "description": "Learned from: Create a note 'Follow up' for alpha",
  "parameters": ["name", "title"],
  "tools": ["find_records", "create_record"],
  "steps": [
    { "tool": "find_records", "args": { "filter": "name = '{{name}}'" } },
    { "tool": "create_record", "args": {
        "kind": "note",
        "parent_id": { "$from": { "step": 0, "path": "rows.0.id" } },
        "title": "{{title}}"
    } }
  ],
  "learned_from": "Create a note 'Follow up' for alpha",
  "created_at": "2026-10-19T09:38:50.521Z",
  "stats": { "runs": 0, "failures": 0, "last_run_at": null }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `format` | yes | Always `1` for this version. Readers reject other values. |
| `intent` | yes | `^[a-z][a-z0-9_]*$`. Unique key of the skill (compared case-insensitively). |
| `parameters` | yes | Names the caller must provide when replaying. |
| `steps` | yes | Non-empty list of `{ "tool": string, "args": object }`, executed in order. |
| `tools` | no | Distinct tools in order of first use. Informational; derived from `steps`. |
| `description`, `learned_from`, `created_at` | no | Informational. `created_at` is ISO 8601 UTC. |
| `stats` | no | Usage counters maintained by the runtime. |

## Replaying

For each step, in order:

1. **Render** `args` (below) using the parameters and the *normalized results* of the steps already run.
2. **Call** the tool through the host's executor.
3. If the call fails (`ok: false`) or raises, **stop**: the replay failed and the host falls back to its agent.
4. Otherwise **normalize** the result content and keep it for the next steps.

The replay succeeds when every step succeeded. Its output is the content of the last step.

### Normalizing a result

- `null` → `null`
- a string, or a non-empty list whose every item has a string `text` (MCP-style parts, joined with `\n`) → parsed
  as JSON when it is valid JSON, kept as text otherwise
- any other value → kept as is

### Rendering arguments

Recursively over objects and arrays:

| Template | Renders to |
| --- | --- |
| a string that is exactly `{{name}}` | the parameter `name`, **type preserved** |
| a string that is exactly `{{@N.path}}` | the value at `path` in step N's result, type preserved |
| a string containing `{{name}}` / `{{@N.path}}` among other text | the text with each placeholder replaced by the **escaped** text form of its value |
| an object whose only key is `$from`: `{"$from": {"step": N, "path": "a.0.b"}}` | the value at `path` in step N's result |
| any other value | itself |

- Placeholder names match `[A-Za-z0-9_@.]+`; whitespace inside the braces is allowed.
- `path` is dot-separated; a numeric segment indexes an array. An empty path means the whole result.
- `N` must be an earlier step. A missing parameter, an unavailable step or a path that does not exist makes the
  replay fail before the tool is called.
- The **text form** of a value is JSON spelling: strings as is, `true`/`false`, `null`, integral numbers without
  a decimal part, objects and arrays as compact JSON.
- Default **escaping** for embedded values: `\` → `\\`, then `'` → `\'`. Hosts may substitute their own.
