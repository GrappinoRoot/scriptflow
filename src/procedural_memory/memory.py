# =========================
# PROCEDURAL MEMORY - the public entry point
# =========================
# An agent that solves the same task twice pays for the reasoning twice. ProceduralMemory
# records the procedure of a successful task, compiles it into a skill and replays it on
# the next matching request: the model is there to find a new solution, not to repeat one
# that was already verified.
#
# The library knows neither your tools nor your model: `classify` and `call_tool` are yours
# and stay yours, so whatever you enforce around tools (permissions, confirmations, guards)
# still applies when the caller is a skill.
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ._util import iso, maybe_await, utc_now
from .compiler import compile_procedure
from .identifiers import DEFAULT_IDENTIFIERS, IdentifierRules
from .intent import DEFAULT_EXAMPLES, Example, Scalar, extract_intent
from .recorder import Recorder, is_successful_run, successful_steps
from .runtime import Escape, escape_embedded, run_skill
from .store import FileStore, SkillStore
from .types import (
    CallTool,
    Classify,
    HandleResult,
    LearnResult,
    RunResult,
    Skill,
    Verdict,
    Verify,
    VerifyContext,
    as_tool_result,
)

log = logging.getLogger("procedural_memory")

Agent = Callable[[CallTool, "Task"], Any]
"""Your agent: (call_tool, task) -> its final answer (sync or async). A str answer ends the run."""


@dataclass
class Task:
    """One request: its classification, the matching skill (if any) and the run recorder."""

    user_message: str
    intent: str | None
    parameters: dict[str, Scalar]
    skill: Skill | None
    recorder: Recorder = field(repr=False)

    # Shortcuts, so an agent loop can record on the task directly
    def record(self, tool: str, args: dict[str, Any], ok: bool, content: Any = None) -> None:
        self.recorder.record_tool_call(tool, args, ok, content)

    def record_skipped(self, tool: str, reason: str) -> None:
        self.recorder.record_skipped(tool, reason)

    def record_final_answer(self, text: str) -> None:
        self.recorder.record_final_answer(text)


class ProceduralMemory:
    """
    Records successful agent runs, compiles them into skills, replays them.

    >>> memory = ProceduralMemory(root="./skills", classify=my_model_call)
    >>> result = await memory.handle("Create a note 'Follow up' for alpha", call_tool=call_tool, agent=agent)
    """

    def __init__(
        self,
        store: SkillStore | None = None,
        *,
        root: str | os.PathLike[str] | None = None,
        classify: Classify | None = None,
        domain_hint: str = "",
        examples: Sequence[Example] = DEFAULT_EXAMPLES,
        identifiers: IdentifierRules = DEFAULT_IDENTIFIERS,
        verify: Verify | None = None,
        escape: Escape = escape_embedded,
    ) -> None:
        """
        store        where skills live (or pass `root` for a FileStore in that directory)
        classify     your model call: (system_prompt, user_message) -> reply text, sync or async
        domain_hint  what the requests are about, for the classification prompt
        examples     worked examples for the classification prompt
        identifiers  how to recognize an opaque id (default: neutral heuristic)
        verify       last word on whether a run may become a skill (see mutation_verifier)
        escape       how a parameter is escaped when embedded in a larger string
        """
        if store is None:
            if root is None:
                raise ValueError("ProceduralMemory needs a 'store' or a 'root' directory")
            store = FileStore(root)
        self.store = store
        self.classify = classify
        self.domain_hint = domain_hint
        self.examples = examples
        self.identifiers = identifiers
        self.verify = verify
        self.escape = escape

    def skills(self) -> list[Skill]:
        """Registered skills."""
        return self.store.all()

    async def resolve(self, user_message: str) -> Task:
        """Classifies the request and looks for a procedure already learned."""
        extracted = None
        if self.classify is not None:
            extracted = await extract_intent(
                user_message,
                self.classify,
                known_skills=self._safe(self.store.all, []),
                domain_hint=self.domain_hint,
                examples=self.examples,
                identifiers=self.identifiers,
            )
        intent = extracted.intent if extracted else None
        return Task(
            user_message=user_message,
            intent=intent,
            parameters=extracted.parameters if extracted else {},
            skill=self._safe(lambda: self.store.get(intent), None) if intent else None,
            recorder=Recorder(user_message),
        )

    def instrument(self, task: Task, call_tool: CallTool) -> CallTool:
        """
        Wraps your call_tool so that every call it makes is recorded on the task. Your agent
        loop stays exactly as it is, and no executed tool can be forgotten. A sync call_tool
        gets a sync wrapper, an async one an async wrapper.
        """

        def record(tool: str, args: dict[str, Any], result: Any) -> Any:
            normalized = as_tool_result(result)
            task.record(tool, args, normalized.ok, normalized.content)
            return result

        def record_error(tool: str, args: dict[str, Any], error: BaseException) -> None:
            # A tool that raises never ran to completion: record a failure and let the
            # exception through, so the caller's error handling is unchanged.
            task.record(tool, args, False, str(error))

        if inspect.iscoroutinefunction(call_tool):

            async def instrumented_async(tool: str, args: dict[str, Any]) -> Any:
                try:
                    result = await call_tool(tool, args)
                except Exception as error:
                    record_error(tool, args, error)
                    raise
                return record(tool, args, result)

            return instrumented_async

        def instrumented(tool: str, args: dict[str, Any]) -> Any:
            try:
                result = call_tool(tool, args)
            except Exception as error:
                record_error(tool, args, error)
                raise
            if inspect.isawaitable(result):
                return _record_later(tool, args, result, record, record_error)
            return record(tool, args, result)

        return instrumented

    async def run(self, task: Task, call_tool: CallTool) -> RunResult:
        """Runs the skill found by resolve() and updates its usage stats."""
        skill = task.skill
        if skill is None:
            return RunResult(ok=False, error="no skill to run")
        result = await run_skill(skill, task.parameters, call_tool, self.escape)
        self._safe(lambda: self._record_usage(skill, result.ok), None)
        return result

    def learn(self, task: Task) -> LearnResult:
        """If the run succeeded, compiles the procedure and registers it."""
        if not task.intent:
            return LearnResult(None, "no intent was extracted")

        trace = task.recorder.trace()
        success = is_successful_run(trace)
        if not success.ok:
            return LearnResult(None, success.reason)

        if self.verify is not None:
            try:
                # The steps that would be compiled, not the path taken to find them
                verdict = self.verify(VerifyContext(task.intent, successful_steps(trace), task.skill))
            except Exception as error:
                # Fail closed: a verifier that breaks must not silently let runs through
                log.warning("procedural-memory: verify raised (%s)", error)
                return LearnResult(None, f"verify failed: {error}")
            if not isinstance(verdict, Verdict) or not verdict.ok:
                return LearnResult(None, getattr(verdict, "reason", "") or "verify refused the run")

        compiled = compile_procedure(task.intent, task.parameters, trace, self.identifiers)
        if not compiled.ok or compiled.skill is None:
            return LearnResult(None, compiled.reason)
        skill = compiled.skill

        # A skill was registered for this intent and we are here, so it failed. Same tools:
        # the procedure is being repaired because the environment moved (a renamed field, a
        # relocated endpoint), replace it. Different tools: another task landed under the
        # same name, keep what already works.
        if task.skill is not None and set(task.skill.tools) != set(skill.tools):
            return LearnResult(
                None,
                f"the registered skill for {task.intent} uses different tools "
                f"({', '.join(task.skill.tools) or 'none'} vs {', '.join(skill.tools)}): not replacing it",
            )

        self.store.save(skill)
        return LearnResult(skill)

    async def handle(self, user_message: str, *, call_tool: CallTool, agent: Agent | None = None) -> HandleResult:
        """
        The whole flow in one call: replay a procedure already learned, or run your agent with
        an instrumented call_tool and learn from it. Equivalent to resolve + run + learn, which
        stay available when you need to drive the steps yourself.
        """
        task = await self.resolve(user_message)

        run: RunResult | None = None
        if task.skill is not None:
            run = await self.run(task, call_tool)
            if run.ok:
                return HandleResult("skill", True, task, output=run.output, run=run)
            # A failed skill is not a failed request: fall back to the agent
            log.info("procedural-memory: skill %s failed (%s), falling back to the agent", task.intent, run.error)

        if agent is None:
            return HandleResult(
                "skill" if run else "agent",
                False,
                task,
                run=run,
                learned=None if run else LearnResult(None, "no agent provided"),
            )

        output = await maybe_await(agent(self.instrument(task, call_tool), task))
        # A string answer is the end of the run; anything else, the agent records itself
        if isinstance(output, str):
            task.record_final_answer(output)
        learned = self.learn(task)
        return HandleResult("agent", True, task, output=output, run=run, learned=learned)

    def handle_sync(self, user_message: str, *, call_tool: CallTool, agent: Agent | None = None) -> HandleResult:
        """handle() for code without an event loop. Do not call it from inside one."""
        return asyncio.run(self.handle(user_message, call_tool=call_tool, agent=agent))

    # --- internals ------------------------------------------------------------------------

    def _record_usage(self, skill: Skill, ok: bool) -> None:
        current = self.store.get(skill.intent) or skill
        stats = replace(
            current.stats,
            runs=current.stats.runs + 1,
            failures=current.stats.failures + (0 if ok else 1),
            last_run_at=iso(utc_now()),
        )
        self.store.save(replace(current, stats=stats))

    @staticmethod
    def _safe(action: Callable[[], Any], fallback: Any) -> Any:
        """Store errors are logged, never raised: the memory must not break the agent."""
        try:
            return action()
        except Exception as error:
            log.warning("procedural-memory: store error (%s)", error)
            return fallback


async def _record_later(
    tool: str,
    args: dict[str, Any],
    pending: Awaitable[Any],
    record: Callable[[str, dict[str, Any], Any], Any],
    record_error: Callable[[str, dict[str, Any], BaseException], None],
) -> Any:
    try:
        result = await pending
    except Exception as error:
        record_error(tool, args, error)
        raise
    return record(tool, args, result)
