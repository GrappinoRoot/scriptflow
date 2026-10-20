# =========================
# COMPILER - from the trace of a successful run to a skill
# =========================
# No model writes the skill: the compiler deterministically turns the recorded steps into
# argument templates. Every argument value must be justifiable:
#   - it comes from a request parameter       → {{param}} placeholder
#   - it comes from an earlier step's result  → {"$from": ...} reference / {{@step.path}}
#   - it is a constant of the procedure (e.g. "kind": "note") → stays literal
# A value that fits none of these and looks like an opaque identifier makes compilation
# fail: a skill that always writes to the same record is not a procedure.
from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._util import is_number, iso, to_text, utc_now
from .identifiers import DEFAULT_IDENTIFIERS, IdentifierRules
from .recorder import successful_steps
from .runtime import PLACEHOLDER, parse_tool_content
from .types import Skill, SkillStep, Trace

VALID_INTENT = re.compile(r"^[a-z][a-z0-9_]*$")

# Small integers (limit, page, retry count) stay constant: they collide too easily with
# some count inside an earlier result.
SMALL_INTEGER = 10


@dataclass
class CompileResult:
    ok: bool
    skill: Skill | None = None
    reason: str = ""


def find_value_paths(value: Any, target: Any, prefix: str = "") -> list[str]:
    """Every dotted path ("records.0.Id") inside `value` holding `target` (compared as text)."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        items: list[tuple[str, Any]] = [(str(k), v) for k, v in value.items()]
    elif isinstance(value, list):
        items = [(str(i), v) for i, v in enumerate(value)]
    else:
        return [prefix] if to_text(value) == to_text(target) else []
    return [
        path for key, child in items for path in find_value_paths(child, target, f"{prefix}.{key}" if prefix else key)
    ]


def find_value_path(value: Any, target: Any) -> str | None:
    """First path of `target` inside `value`, or None."""
    paths = find_value_paths(value, target)
    return paths[0] if paths else None


def _locate(value: Any, ctx: _Context, identifier: bool = False) -> tuple[int, str] | None:
    """
    Most recent earlier step whose result holds `value`. Plain values (names, words, numbers)
    are only taken from steps that depend on the request: a step that does not returns the
    same thing on every run, so linking to it adds fragility and nothing else (a constant
    "Task" would end up read from some position inside a schema). Identifiers come from any
    step: the current user's id, read by a step without parameters, must still be linked.
    """
    for step in range(len(ctx.previous) - 1, -1, -1):
        if not (identifier or ctx.dependent[step]):
            continue
        path = find_value_path(ctx.previous[step], value)
        if path is not None:
            ctx.step_dependent = ctx.step_dependent or ctx.dependent[step]
            return step, path
    return None


def _step_placeholder(step: int, path: str) -> str:
    return f"{{{{@{step}.{path}}}}}" if path else f"{{{{@{step}}}}}"


def _outside_placeholders(text: str, transform: Callable[[str], str]) -> str:
    """Applies `transform` to the text between placeholders, never inside one."""
    out, last = [], 0
    for match in PLACEHOLDER.finditer(text):
        out.append(transform(text[last : match.start()]))
        out.append(match.group(0))
        last = match.end()
    out.append(transform(text[last:]))
    return "".join(out)


@dataclass
class _Context:
    parameters: list[tuple[str, Any]]
    identifiers: IdentifierRules
    previous: list[Any] = field(default_factory=list)
    """Normalized results of the steps compiled so far."""
    dependent: list[bool] = field(default_factory=list)
    """For each of those steps: do its arguments depend on the request?"""
    step_dependent: bool = False
    """The same, for the step being compiled."""
    used: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)


def _apply_parameters(text: str, ctx: _Context) -> tuple[str, bool]:
    """
    Replaces occurrences of parameter values with their placeholders. A value matches only
    as a whole token (not inside a longer word), longest values first, and never inside a
    placeholder already written.
    """
    replaced = False
    for name, raw in sorted(ctx.parameters, key=lambda entry: -len(to_text(entry[1]))):
        value = to_text(raw)
        if not value:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(value) + r"(?!\w)", re.IGNORECASE)
        hit = False

        def substitute(segment: str, pattern: re.Pattern[str] = pattern, name: str = name) -> str:
            nonlocal hit
            new, count = pattern.subn(lambda _m: f"{{{{{name}}}}}", segment)
            hit = hit or count > 0
            return new

        text = _outside_placeholders(text, substitute)
        if hit:
            ctx.used.add(name)
            ctx.step_dependent = True
            replaced = True
    return text, replaced


def _check_fragments(text: str, key_path: str, ctx: _Context) -> None:
    """
    A literal that holds a piece of a parameter but not the parameter itself means the agent
    transformed the request ("Alpha Beta Gamma" → "like '%Beta%'") in a way the
    skill cannot reproduce: replayed for another name, it would still search for "Beta" and act
    on the wrong record. Refused rather than guessed.
    """
    literal_words = {w.lower() for w in re.findall(r"\w+", PLACEHOLDER.sub(" ", text))}
    for name, raw in ctx.parameters:
        if not isinstance(raw, str):
            continue
        fragments = {w.lower() for w in re.findall(r"\w{3,}", raw)} & literal_words
        if fragments and f"{{{{{name}}}}}" not in text:
            ctx.problems.append(
                f"argument {key_path or '(root)'} contains {', '.join(repr(f) for f in sorted(fragments))}, "
                f"part of the parameter {name} ({raw!r}) but not the whole value: "
                "the agent transformed the request in a way the skill cannot replay"
            )


def _replace_embedded_ids(text: str, key_path: str, ctx: _Context) -> str:
    """
    Identifiers left literal inside a larger string (typically `WHERE Id = '001...'` in a
    query) become references to the step that produced them. An identifier that comes from
    nowhere is a problem: baked into the skill, it would always hit the same record.
    """

    def replacer(identifier: str) -> str:
        located = _locate(identifier, ctx, identifier=True)
        if located:
            return _step_placeholder(*located)
        ctx.problems.append(
            f"argument {key_path or '(root)'} contains the identifier {identifier}, "
            "which comes neither from a parameter nor from an earlier step"
        )
        return identifier

    return _outside_placeholders(text, lambda segment: ctx.identifiers.replace(segment, replacer))


def _numeric_reference(value: Any, ctx: _Context) -> dict[str, Any] | None:
    """
    A number may come from an earlier step (coordinates, amounts, numeric ids). Three
    safeguards: small integers stay constant, the step must depend on the request, and the
    value must appear exactly once in its result. Booleans are never linked: they are flags
    of the procedure.
    """
    if not is_number(value) or not math.isfinite(value):
        return None
    if float(value).is_integer() and abs(value) <= SMALL_INTEGER:
        return None
    for step in range(len(ctx.previous) - 1, -1, -1):
        if not ctx.dependent[step]:
            continue
        paths = find_value_paths(ctx.previous[step], value)
        if len(paths) == 1:
            ctx.step_dependent = True
            return {"$from": {"step": step, "path": paths[0]}}
    return None


def _compile_value(value: Any, key_path: str, ctx: _Context) -> Any:
    if isinstance(value, list):
        return [_compile_value(item, f"{key_path}[{i}]", ctx) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            key: _compile_value(child, f"{key_path}.{key}" if key_path else str(key), ctx)
            for key, child in value.items()
        }
    if not isinstance(value, str):
        # A number or a flag can be a request parameter, or (numbers only) an earlier result
        # (compared as JSON text, so True never matches 1)
        for name, parameter in ctx.parameters:
            if to_text(parameter) == to_text(value):
                ctx.used.add(name)
                ctx.step_dependent = True
                return f"{{{{{name}}}}}"  # placeholder on its own: render_args keeps the type
        return _numeric_reference(value, ctx) or value

    text, replaced = _apply_parameters(value, ctx)
    if not replaced and text:
        # Whole value taken from an earlier step (an id just read, a name, a field)
        located = _locate(text, ctx, identifier=ctx.identifiers.find(text) == text)
        if located:
            return {"$from": {"step": located[0], "path": located[1]}}
    # What is left are identifiers nested in larger strings: queries are the typical case
    text = _replace_embedded_ids(text, key_path, ctx)
    _check_fragments(text, key_path, ctx)
    return text


def compile_procedure(
    intent: str,
    parameters: Mapping[str, Any],
    trace: Trace,
    identifiers: IdentifierRules = DEFAULT_IDENTIFIERS,
    now: Callable[[], datetime] = utc_now,
) -> CompileResult:
    """Compiles the trace of a successful run into a Skill, or explains why it cannot."""
    if not VALID_INTENT.match(intent or ""):
        return CompileResult(False, reason=f"invalid intent: {intent!r}")
    # Successful steps only: a failed attempt changed nothing and must not be replayed.
    # Filtering before the loop keeps the {"$from": {"step": n}} indexes consistent.
    steps = successful_steps(trace)
    if not steps:
        return CompileResult(False, reason="empty trace: no successful step to compile")

    ctx = _Context(
        parameters=[(k, v) for k, v in parameters.items() if v is not None and v != ""],
        identifiers=identifiers,
    )
    compiled: list[SkillStep] = []
    for step in steps:
        ctx.step_dependent = False
        compiled.append(SkillStep(tool=step.tool, args=_compile_value(step.args or {}, "", ctx)))
        ctx.previous.append(parse_tool_content(step.content))
        ctx.dependent.append(ctx.step_dependent)

    unused = [name for name, _ in ctx.parameters if name not in ctx.used]
    if unused:
        ctx.problems.append(
            f"parameters {', '.join(unused)} appear in no argument: the procedure would not depend on the request"
        )
    if ctx.problems:
        return CompileResult(False, reason="; ".join(ctx.problems))

    return CompileResult(
        True,
        skill=Skill(
            intent=intent,
            parameters=[name for name, _ in ctx.parameters],
            steps=compiled,
            description=f"Learned from: {trace.user_message}",
            learned_from=trace.user_message,
            created_at=iso(now()),
        ),
    )
