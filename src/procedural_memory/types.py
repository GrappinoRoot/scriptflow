# =========================
# TYPES - the data the library passes around
# =========================
# Plain dataclasses, no behaviour beyond (de)serialization. A Skill is pure data: the JSON
# file described in SPEC.md, readable and editable by hand, portable across languages.
from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

SKILL_FORMAT = 1

# --- What the host provides -------------------------------------------------------------


@dataclass(frozen=True)
class ToolResult:
    """What a tool call returned. `content` can be MCP-style parts, a string or any JSON value."""

    ok: bool
    content: Any = None


ToolResultLike = ToolResult | Mapping[str, Any]
"""A ToolResult, or a mapping with the same keys: {"ok": bool, "content": ...}."""

CallTool = Callable[[str, dict[str, Any]], ToolResultLike | Awaitable[ToolResultLike]]
"""Your tool executor, sync or async. The library never calls a tool any other way."""

Classify = Callable[[str, str], str | Awaitable[str]]
"""Your model call: (system_prompt, user_message) -> the model's text reply. Sync or async."""


def as_tool_result(value: Any) -> ToolResult:
    """Accepts a ToolResult, a mapping, or any object with `ok`/`content` attributes."""
    if isinstance(value, ToolResult):
        return value
    if isinstance(value, Mapping):
        return ToolResult(ok=bool(value.get("ok")), content=value.get("content"))
    if hasattr(value, "ok"):
        return ToolResult(ok=bool(value.ok), content=getattr(value, "content", None))
    raise TypeError(f"call_tool must return a ToolResult or a mapping with 'ok', got {type(value).__name__}")


# --- Recording --------------------------------------------------------------------------


@dataclass
class RecordedStep:
    """A tool call observed during an agent run."""

    tool: str
    args: dict[str, Any]
    ok: bool
    content: Any = None
    skipped: bool = False
    reason: str = ""


@dataclass
class Trace:
    user_message: str
    steps: list[RecordedStep]
    final_answer: str


@dataclass(frozen=True)
class Verdict:
    """Outcome of a check: ok, or not ok with the reason why."""

    ok: bool
    reason: str = ""


# --- Skills -----------------------------------------------------------------------------


@dataclass
class SkillStep:
    """One step of a compiled skill: a tool and its argument template."""

    tool: str
    args: dict[str, Any]


@dataclass
class SkillStats:
    runs: int = 0
    failures: int = 0
    last_run_at: str | None = None


@dataclass
class Skill:
    """A learned procedure. Serialized as the JSON document described in SPEC.md."""

    intent: str
    parameters: list[str]
    steps: list[SkillStep]
    description: str = ""
    learned_from: str = ""
    created_at: str = ""
    stats: SkillStats = field(default_factory=SkillStats)
    format: int = SKILL_FORMAT

    @property
    def tools(self) -> list[str]:
        """The distinct tools the skill calls, in order of first use."""
        return list(dict.fromkeys(step.tool for step in self.steps))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "intent": self.intent,
            "description": self.description,
            "parameters": list(self.parameters),
            "tools": self.tools,
            "steps": [{"tool": s.tool, "args": s.args} for s in self.steps],
            "learned_from": self.learned_from,
            "created_at": self.created_at,
            "stats": {
                "runs": self.stats.runs,
                "failures": self.stats.failures,
                "last_run_at": self.stats.last_run_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Skill:
        """Builds a Skill from its JSON form. Raises ValueError when the document is invalid."""
        if not isinstance(data, Mapping):
            raise ValueError("a skill must be a JSON object")
        fmt = data.get("format", SKILL_FORMAT)
        if fmt != SKILL_FORMAT:
            raise ValueError(f"unsupported skill format {fmt!r} (this library reads format {SKILL_FORMAT})")
        intent = data.get("intent")
        if not isinstance(intent, str) or not intent:
            raise ValueError("a skill needs a non-empty 'intent'")
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError(f"skill {intent}: 'steps' must be a non-empty list")
        steps = []
        for i, step in enumerate(raw_steps):
            if not isinstance(step, Mapping) or not isinstance(step.get("tool"), str):
                raise ValueError(f"skill {intent}: step {i} needs a 'tool'")
            args = step.get("args", {})
            if not isinstance(args, dict):
                raise ValueError(f"skill {intent}: step {i} 'args' must be an object")
            # Copied: a Skill never shares mutable state with the document it was read from
            steps.append(SkillStep(tool=step["tool"], args=copy.deepcopy(args)))
        parameters = data.get("parameters", [])
        if not isinstance(parameters, list) or not all(isinstance(p, str) for p in parameters):
            raise ValueError(f"skill {intent}: 'parameters' must be a list of names")
        stats = data.get("stats") or {}
        return cls(
            intent=intent,
            parameters=parameters,
            steps=steps,
            description=str(data.get("description", "")),
            learned_from=str(data.get("learned_from", "")),
            created_at=str(data.get("created_at", "")),
            stats=SkillStats(
                runs=int(stats.get("runs", 0) or 0),
                failures=int(stats.get("failures", 0) or 0),
                last_run_at=stats.get("last_run_at"),
            ),
        )


# --- Results ----------------------------------------------------------------------------


@dataclass
class ExecutedStep:
    """A step a skill actually ran, with the arguments it rendered."""

    tool: str
    args: dict[str, Any]
    ok: bool
    content: Any = None


@dataclass
class RunResult:
    ok: bool
    steps: list[ExecutedStep] = field(default_factory=list)
    failed_step: str | None = None
    error: str | None = None

    @property
    def output(self) -> Any:
        """Content of the last executed step: what the skill produced."""
        return self.steps[-1].content if self.steps else None


@dataclass
class LearnResult:
    saved: Skill | None
    reason: str = ""


@dataclass
class HandleResult:
    """What handle() returns: the outcome plus how it was produced."""

    source: Literal["skill", "agent"]
    ok: bool
    task: Any  # Task, kept as Any to avoid an import cycle with memory.py
    output: Any = None
    run: RunResult | None = None
    learned: LearnResult | None = None


@dataclass(frozen=True)
class VerifyContext:
    intent: str
    steps: list[RecordedStep]
    """The successful steps, i.e. the ones that would be compiled."""
    skill: Skill | None
    """The skill already registered for this intent, when there is one."""


Verify = Callable[[VerifyContext], Verdict]
"""Your last word on whether a run may become a skill. Raising refuses the run."""
