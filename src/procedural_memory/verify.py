# =========================
# VERIFY - ready-made check for the most common false success
# =========================
# A run can be structurally perfect and still not have done the job: the agent queries,
# reads a schema, then answers "which first name should I use?". is_successful_run says ok,
# because nothing was blocked and an answer came back. Compiled, that becomes a
# `create_contact` skill that creates no contact and runs instead of the agent.
#
# The library cannot judge semantics, but it can check the intent's verb against the
# observed effects, provided the host says which of its tools change state.
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from .types import Verdict, Verify, VerifyContext

MUTATION_VERBS: tuple[str, ...] = ("create", "update", "delete", "remove", "add", "set", "send", "assign")
"""Intent prefixes that promise a change."""


def implies_mutation(intent: str, verbs: tuple[str, ...] = MUTATION_VERBS) -> bool:
    """True when the intent's verb promises a change (`create_contact`, `delete`, `send_email`)."""
    return re.match(rf"^({'|'.join(map(re.escape, verbs))})(_|$)", str(intent or "").lower()) is not None


def mutation_verifier(
    is_mutation: Callable[[str, dict[str, Any]], bool],
    verbs: tuple[str, ...] = MUTATION_VERBS,
) -> Verify:
    """
    A `verify` that refuses a run whose intent promises a change when no mutating tool ran.
    `is_mutation(tool, args)` is yours, because only you know your tools: it gets the
    arguments too, since a generic tool (a `rest_call`, an `execute`) writes or not depending
    on them, not on its name.
    """
    if not callable(is_mutation):
        raise TypeError("mutation_verifier: 'is_mutation' must be a function (tool, args) -> bool")

    def verify(context: VerifyContext) -> Verdict:
        if not implies_mutation(context.intent, verbs):
            return Verdict(True)
        # Only successful steps are passed in: a write that failed changed nothing either.
        if any(is_mutation(step.tool, step.args) for step in context.steps):
            return Verdict(True)
        return Verdict(
            False, f"intent '{context.intent}' implies a change but no mutating tool ran: the task was not performed"
        )

    return verify
