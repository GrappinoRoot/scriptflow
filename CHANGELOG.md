# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-19

Python rewrite of `@script-flow/procedural-memory` 0.2.1, published on PyPI as
`scriptflow-procedural-memory`. Same model, same safety rules, same placeholder language.

### Changed

- **Skills are JSON documents** ([SPEC.md](SPEC.md)) instead of generated `.mjs` scripts: no generated
  code is ever imported or executed, and a skill can be stored anywhere and replayed by any implementation.
- `classify(system, user) -> str` replaces the ollama-shaped `chat` option. Adapters for OpenAI,
  Anthropic and Ollama clients are in `procedural_memory.adapters`.
- Storage is pluggable (`SkillStore` protocol). `FileStore` writes one file per skill, atomically;
  `MemoryStore` keeps skills in memory. The shared `registry.json` is gone.
- Every callback (`classify`, `call_tool`, `agent`, `verify`'s `is_mutation`) may be sync or async.
  `handle_sync()` for code without an event loop.
- Logging uses the standard `logging` module (`procedural_memory` logger).

### Fixed

- A literal holding a piece of a parameter but not the whole value ("Alpha Beta Gamma" →
  `like '%Beta%'`) now refuses the skill: replayed for another request, it would have acted on the
  record the first run found.
- Names, words and numbers are linked only to earlier steps that depend on the request. A step
  without parameters returns the same thing every run, so linking to it only added fragility (a
  constant was read from an arbitrary position inside a schema). Identifiers are still linked from
  any step.
- A parameter value now matches inside a string only as a whole token: a short value no longer
  rewrites unrelated words of a query. Longer values are matched first, and never inside a placeholder
  already written.
- Booleans are compared with JSON spelling, so `True` never matches `1`.
- Recorded arguments are copied, so an agent loop mutating its dict after the call cannot alter the trace.
- An intent is validated before it becomes a file name.

### Added

- `procedural-memory` CLI: `list`, `show`, `delete`, and `import-legacy` to convert skills learned by the
  npm package 0.x.
