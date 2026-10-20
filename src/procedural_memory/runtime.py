# =========================
# RUNTIME - replaying a compiled skill
# =========================
# A skill contains no code: a list of steps (tool + argument template). The runtime turns
# each template into real arguments from the request parameters and the results of earlier
# steps, then calls the host's call_tool. No eval, no import of generated files.
#
# Placeholder language (see SPEC.md):
#   "{{name}}"                       → the whole value is the `name` parameter (type preserved)
#   "... '{{name}}' ..."             → parameter embedded in a larger string (escaped)
#   "... '{{@0.records.0.Id}}' ..."  → value read from step 0's result
#   {"$from": {"step": 0, "path": "records.0.Id"}} → same, when it is the entire argument value
#
# Every tool call goes through your call_tool, so whatever guards you have around tools
# (permissions, confirmations, auditing) still apply. Any failure becomes RunResult(ok=False)
# so the caller can fall back to its agent.
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from ._util import MISSING, maybe_await, to_text
from .types import CallTool, ExecutedStep, RunResult, Skill, as_tool_result

PLACEHOLDER_NAME = r"[A-Za-z0-9_@.]+"
PLACEHOLDER = re.compile(r"\{\{\s*(" + PLACEHOLDER_NAME + r")\s*\}\}")
EXACT_PLACEHOLDER = re.compile(r"^\{\{\s*(" + PLACEHOLDER_NAME + r")\s*\}\}$")

Escape = Callable[[Any], str]


class SkillParameterError(Exception):
    """A placeholder could not be resolved: missing parameter or unknown path."""


def escape_embedded(value: Any) -> str:
    """
    Escapes a value interpolated into a larger string (typically a query): a quote inside the
    value must not break, or alter, the surrounding statement.
    """
    return to_text(value).replace("\\", "\\\\").replace("'", "\\'")


def _part_text(part: Any) -> str | None:
    # MCP SDK objects (TextContent) carry .text, JSON parts carry ["text"]
    text = part.get("text") if isinstance(part, Mapping) else getattr(part, "text", None)
    return text if isinstance(text, str) else None


def parse_tool_content(content: Any) -> Any:
    """
    Normalizes a tool result into a JSON value. Text (a string, or MCP-style parts) is parsed as
    JSON when possible and returned as text otherwise; structured values are returned as they
    are. Used both at compile time and at run time, so recorded paths still resolve on replay.
    """
    if content is None:
        return None
    if isinstance(content, str):
        text = content
    elif isinstance(content, (list, tuple)) and content and all(_part_text(p) is not None for p in content):
        text = "\n".join(_part_text(p) or "" for p in content)
    else:
        return content
    try:
        return json.loads(text)
    except ValueError:
        return text


def get_at_path(value: Any, dotted_path: str, default: Any = None) -> Any:
    """Reads a nested value through a dotted path ("records.0.Id"); `default` when absent."""
    found = _lookup(value, dotted_path)
    return default if found is MISSING else found


def _lookup(value: Any, dotted_path: str) -> Any:
    if not dotted_path:
        return value
    current = value
    for key in dotted_path.split("."):
        if isinstance(current, list):
            if not key.isdigit() or int(key) >= len(current):
                return MISSING
            current = current[int(key)]
        elif isinstance(current, Mapping):
            if key not in current:
                return MISSING
            current = current[key]
        else:
            return MISSING
    return current


def _resolve_step_reference(step: Any, path: str, step_results: Sequence[Any]) -> Any:
    if not isinstance(step, int) or isinstance(step, bool) or not 0 <= step < len(step_results):
        raise SkillParameterError(f"Reference to step {step} is not available")
    value = _lookup(step_results[step], path)
    if value is MISSING:
        raise SkillParameterError(f'Path "{path}" not found in the result of step {step}')
    return value


def _resolve_placeholder(name: str, params: Mapping[str, Any], step_results: Sequence[Any]) -> Any:
    if name.startswith("@"):
        step, _, path = name[1:].partition(".")
        if not step.isdigit():
            raise SkillParameterError(f"Invalid step reference: {name}")
        return _resolve_step_reference(int(step), path, step_results)
    if name not in params:
        raise SkillParameterError(f"Missing parameter: {name}")
    return params[name]


def render_args(
    template: Any,
    params: Mapping[str, Any] | None = None,
    step_results: Sequence[Any] = (),
    escape: Escape = escape_embedded,
) -> Any:
    """
    Computes the real arguments of a step, resolving placeholders and step references.
    Raises SkillParameterError when a parameter is missing or a reference does not resolve.
    """
    params = params or {}
    if isinstance(template, str):
        exact = EXACT_PLACEHOLDER.match(template)
        if exact:
            return _resolve_placeholder(exact.group(1), params, step_results)  # type preserved
        return PLACEHOLDER.sub(lambda m: escape(_resolve_placeholder(m.group(1), params, step_results)), template)
    if isinstance(template, list):
        return [render_args(item, params, step_results, escape) for item in template]
    if isinstance(template, dict):
        ref = template.get("$from")
        if isinstance(ref, Mapping) and len(template) == 1:
            return _resolve_step_reference(ref.get("step"), str(ref.get("path", "")), step_results)
        return {key: render_args(value, params, step_results, escape) for key, value in template.items()}
    return template


async def run_skill(
    skill: Skill,
    params: Mapping[str, Any],
    call_tool: CallTool,
    escape: Escape = escape_embedded,
) -> RunResult:
    """Replays a skill through the host's call_tool. Never raises: failures are RunResult(ok=False)."""
    missing = [name for name in skill.parameters if name not in params]
    if missing:
        return RunResult(ok=False, error=f"missing parameters: {', '.join(missing)}")

    executed: list[ExecutedStep] = []
    results: list[Any] = []
    for step in skill.steps:
        try:
            args = render_args(step.args, params, results, escape)
        except SkillParameterError as error:
            return RunResult(ok=False, steps=executed, failed_step=step.tool, error=str(error))
        try:
            result = as_tool_result(await maybe_await(call_tool(step.tool, args)))
        except Exception as error:
            return RunResult(ok=False, steps=executed, failed_step=step.tool, error=f"{step.tool} raised: {error}")
        executed.append(ExecutedStep(tool=step.tool, args=args, ok=result.ok, content=result.content))
        results.append(parse_tool_content(result.content))
        if not result.ok:
            return RunResult(ok=False, steps=executed, failed_step=step.tool, error=f"{step.tool} failed")
    return RunResult(ok=True, steps=executed)
