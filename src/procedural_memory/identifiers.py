# =========================
# IDENTIFIERS - spotting opaque identifiers inside tool arguments
# =========================
# An identifier (a record id, a foreign key) baked into a skill would make it useless: the
# skill would always operate on the same object. The compiler must therefore recognize
# them, but every domain has its own format, so the caller can pass its own rule.
#
# The default is a neutral heuristic: an alphanumeric token of at least 12 characters that
# contains both letters and digits (a generated id, not a word). If you know your format,
# replace it: `RegexIdentifiers(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")`.
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class IdentifierRules(Protocol):
    """How to recognize an opaque identifier inside a piece of text."""

    def find(self, text: str) -> str | None:
        """First identifier contained in the text, or None."""
        ...

    def replace(self, text: str, replacer: Callable[[str], str]) -> str:
        """The text with every identifier passed through `replacer`."""
        ...


class RegexIdentifiers:
    """Identifiers are the matches of `pattern` that `accept` agrees with."""

    def __init__(self, pattern: str | re.Pattern[str], accept: Callable[[str], bool] | None = None) -> None:
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.accept = accept or (lambda _token: True)

    def find(self, text: str) -> str | None:
        for match in self.pattern.finditer(text):
            if self.accept(match.group(0)):
                return match.group(0)
        return None

    def replace(self, text: str, replacer: Callable[[str], str]) -> str:
        def substitute(match: re.Match[str]) -> str:
            token = match.group(0)
            return replacer(token) if self.accept(token) else token

        return self.pattern.sub(substitute, text)


def _looks_generated(token: str) -> bool:
    return any(c.isdigit() for c in token) and any(c.isalpha() for c in token)


DEFAULT_IDENTIFIERS = RegexIdentifiers(r"\b[A-Za-z0-9]{12,}\b", accept=_looks_generated)
