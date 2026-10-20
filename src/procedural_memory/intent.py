# =========================
# INTENT - user request → (intent, parameters)
# =========================
# The only model call on the fast path: it classifies the request and extracts its
# variables. The catalog of known skills is part of the prompt, so the model reuses an
# intent already registered instead of coining a new name for the same procedure.
# Anything going wrong (model offline, invalid JSON) returns None: the caller simply
# continues with its normal path.
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._util import maybe_await
from .compiler import VALID_INTENT
from .identifiers import DEFAULT_IDENTIFIERS, IdentifierRules
from .types import Classify, Skill

log = logging.getLogger("procedural_memory")

Scalar = str | int | float | bool

VALID_PARAMETER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Example:
    """A worked example for the classification prompt."""

    request: str
    intent: str
    parameters: Mapping[str, Scalar]


@dataclass(frozen=True)
class Intent:
    intent: str
    parameters: dict[str, Scalar]


DEFAULT_EXAMPLES = (Example("Find the record named alpha", "find_record", {"name": "alpha"}),)


def build_intent_prompt(
    known_skills: Iterable[Skill] = (),
    domain_hint: str = "",
    examples: Sequence[Example] = DEFAULT_EXAMPLES,
) -> str:
    """The system prompt used to classify a request."""
    catalog = (
        "\n".join(f"- {s.intent}({', '.join(s.parameters)}): {s.description}" for s in known_skills)
        or "(no procedure registered yet)"
    )
    domain = f" The requests concern {domain_hint}." if domain_hint else ""
    shown = "\n\n".join(
        f"Request: {e.request}\n{json.dumps({'intent': e.intent, 'parameters': dict(e.parameters)})}" for e in examples
    )
    return f"""You classify user requests.{domain} Reply with JSON only: {{"intent": "...", "parameters": {{...}}}}.

RULES:
1. "intent" is a snake_case verb_object name describing the task type (e.g. find_record, create_note_for_record).
2. If the request matches one of the known procedures below, reuse its exact intent name and fill its parameters.
3. "parameters" holds the values taken literally from the request (record names, subjects, quantities), never invented ones.
4. Parameter values must be copied verbatim from the request text, without quotes or extra words.
5. Do not add commentary.

KNOWN PROCEDURES:
{catalog}

EXAMPLES
{shown}"""


def normalize_parameter_value(value: Scalar, identifiers: IdentifierRules = DEFAULT_IDENTIFIERS) -> Scalar:
    """
    Strips what the model added around a parameter value: surrounding quotes, and words
    around an identifier ("Order A7f3k2m9x1q8" → "A7f3k2m9x1q8"). Without this the value does
    not match what actually reached the tool arguments, and the procedure cannot be compiled.
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    quoted = re.fullmatch(r"([\"'])(.*)\1", text, re.DOTALL)
    if quoted:
        text = quoted.group(2).strip()
    found = identifiers.find(text)
    return found if found and found != text else text


def _parse_json_object(reply: str) -> Any:
    """The JSON object in the model's reply, tolerating code fences and stray text around it."""
    text = reply.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])


async def extract_intent(
    user_message: str,
    classify: Classify,
    known_skills: Iterable[Skill] = (),
    domain_hint: str = "",
    examples: Sequence[Example] = DEFAULT_EXAMPLES,
    identifiers: IdentifierRules = DEFAULT_IDENTIFIERS,
) -> Intent | None:
    """Classifies the request. None when nothing usable came back."""
    if not user_message:
        return None
    try:
        system = build_intent_prompt(known_skills, domain_hint, examples)
        parsed = _parse_json_object(await maybe_await(classify(system, user_message)))
        if not isinstance(parsed, Mapping):
            return None
        intent = re.sub(r"\s+", "_", str(parsed.get("intent", "")).strip().lower())
        raw = parsed.get("parameters", {})
        if not VALID_INTENT.match(intent) or not isinstance(raw, Mapping):
            return None
        parameters = {
            key: normalize_parameter_value(value, identifiers)
            for key, value in raw.items()
            if isinstance(key, str) and VALID_PARAMETER.match(key) and isinstance(value, (str, int, float, bool))
        }
        return Intent(intent, parameters)
    except Exception as error:
        log.warning("procedural-memory: intent extraction failed (%s)", error)
        return None
