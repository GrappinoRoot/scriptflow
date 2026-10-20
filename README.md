# procedural-memory

**Give your AI agent a memory of how it solves tasks.**

`procedural-memory` saves successful tasks as reusable skills. When a similar request comes in, it replays the saved steps instead of asking the LLM to solve the same problem again.

**Solve it once. Reuse it next time.**

```
USER REQUEST
      │
 intent + parameters ← one cheap classification call
      │
 ┌────┴─────┐
 │  STORE   │
 └────┬─────┘
   ┌──┴──┐
MATCH    NO MATCH
   │          │
SKILL       AGENT → success check → compile → STORE
   │          │
   └────┬─────┘
      RESULT
```

## How it works

1. Your agent receives a request.
2. The library checks whether a matching skill already exists.
3. If a skill matches, it replays the saved tool calls.
4. If no skill matches, your agent solves the task.
5. If the task succeeds, the library saves it as a reusable skill.

## Features

- **Save reasoning costs** — reuse previous solutions instead of solving the same task again.
- **Works with any LLM** — you provide your own `classify` and `call_tool` functions.
- **No dependencies** — only Python 3.10+ is required.
- **Sync and async** — supports both synchronous and asynchronous functions.
- **Safe by design** — skills contain JSON tool calls, not executable code.
- **Human-readable skills** — inspect and edit saved procedures manually.
- **Keep control** — your existing permissions, confirmations, rate limits and auditing still apply.

Skills are learned only from successful executions. A skill is not saved if it depends on a fixed identifier or contains unused request parameters.

## Install

```bash
pip install scriptflow-procedural-memory
```

## Documentation

See [SPEC.md](SPEC.md) for the skill format and technical details.

## License

MIT