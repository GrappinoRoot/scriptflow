# =========================
# ADAPTERS - turn a provider client into a `classify` function
# =========================
# `classify` is just (system_prompt, user_message) -> reply text, so any model works. These
# helpers save the boilerplate for the common SDKs. They import nothing: you pass the client
# you already have, sync or async, and the helper returns a function of the same kind.
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from .types import Classify


def _then(value: Any, extract: Callable[[Any], str]) -> Any:
    """Applies `extract` to a value, or to its result when the client is async."""
    if inspect.isawaitable(value):

        async def finish() -> str:
            return extract(await value)

        return finish()
    return extract(value)


def openai_classifier(client: Any, model: str, **options: Any) -> Classify:
    """For `openai.OpenAI` / `openai.AsyncOpenAI` and any OpenAI-compatible server."""

    def classify(system: str, user: str) -> Any:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            **options,
        )
        return _then(response, lambda r: r.choices[0].message.content or "")

    return classify


def anthropic_classifier(client: Any, model: str, max_tokens: int = 1024, **options: Any) -> Classify:
    """For `anthropic.Anthropic` / `anthropic.AsyncAnthropic`."""

    def classify(system: str, user: str) -> Any:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **options,
        )
        return _then(response, lambda r: "".join(b.text for b in r.content if b.type == "text"))

    return classify


def ollama_classifier(client: Any, model: str, **options: Any) -> Classify:
    """For the `ollama` module, `ollama.Client` or `ollama.AsyncClient`."""

    def classify(system: str, user: str) -> Any:
        response = client.chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            format="json",
            **options,
        )
        return _then(response, lambda r: r["message"]["content"] or "")

    return classify
