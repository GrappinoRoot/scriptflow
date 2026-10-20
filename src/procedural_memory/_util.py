# Small helpers shared by every module. Private: not part of the public API.
from __future__ import annotations

import inspect
import json
import math
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, TypeVar, cast

T = TypeVar("T")


class _Missing:
    """Marks a value that does not exist, as opposed to a JSON null (None)."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING: Any = _Missing()


async def maybe_await(value: T | Awaitable[T]) -> T:
    """Lets every callback the host passes in be either sync or async."""
    if inspect.isawaitable(value):
        return await cast(Awaitable[T], value)
    return value


def to_text(value: Any) -> str:
    """
    The textual form of a JSON value, the same everywhere a value is compared or embedded.
    It follows JSON spelling rather than Python's (`true`, not `True`; `5`, not `5.0`), so a
    skill compiled here matches what any other implementation of the format would produce.
    """
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def is_number(value: Any) -> bool:
    """int or float, but not bool: in Python bool is a subclass of int."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    """ISO 8601 in UTC with milliseconds and a trailing Z."""
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
