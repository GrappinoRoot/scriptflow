# =========================
# RECORDER - trace of one agent run + success check
# =========================
# Records the procedure the agent loop actually executed (which tools, with which arguments,
# with which result). The trace is the compiler's input: only successful runs become
# skills, so the registry never learns a broken procedure.
from __future__ import annotations

import copy
from typing import Any

from .types import RecordedStep, Trace, Verdict


class Recorder:
    """Collects the steps of a single agent run."""

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        self._steps: list[RecordedStep] = []
        self._final_answer = ""

    def record_tool_call(self, tool: str, args: dict[str, Any], ok: bool, content: Any = None) -> None:
        """Records a tool that really ran (after your guards allowed it)."""
        # Copied: the agent loop may mutate its argument dict after the call.
        self._steps.append(RecordedStep(tool=tool, args=copy.deepcopy(args), ok=bool(ok), content=content))

    def record_skipped(self, tool: str, reason: str) -> None:
        """
        Records a tool that did NOT run (blocked by a guard, denied by the user, malformed
        arguments): it makes the run non-compilable.
        """
        self._steps.append(RecordedStep(tool=tool, args={}, ok=False, skipped=True, reason=reason))

    def record_final_answer(self, text: str) -> None:
        """Records the model's final answer (end of the loop)."""
        self._final_answer = text.strip() if isinstance(text, str) else ""

    def trace(self) -> Trace:
        return Trace(user_message=self.user_message, steps=list(self._steps), final_answer=self._final_answer)


def is_successful_run(trace: Trace) -> Verdict:
    """
    Deterministic check that the run succeeded and may become a skill: at least one successful
    tool, no blocked or denied step, a final answer. A failed step does NOT invalidate the run:
    an agent that mistypes a call and then corrects itself is the normal case, and the failed
    attempt changed nothing. What gets compiled is the working procedure (successful_steps).
    """
    steps = trace.steps
    if not steps:
        return Verdict(False, "no tool was executed: nothing to record")
    skipped = next((s for s in steps if s.skipped), None)
    if skipped:
        return Verdict(False, f"step not executed ({skipped.tool}): {skipped.reason}")
    if not any(s.ok for s in steps):
        return Verdict(False, f"no tool succeeded (last one: {steps[-1].tool})")
    if not trace.final_answer:
        return Verdict(False, "no final answer from the model")
    return Verdict(True)


def successful_steps(trace: Trace) -> list[RecordedStep]:
    """The steps to compile: the successful ones, in their original order."""
    return [s for s in trace.steps if s.ok]
