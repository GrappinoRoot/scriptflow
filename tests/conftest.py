"""A tiny fake tool backend shared by the tests: two tools, a classifier and an agent."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from procedural_memory import ToolResult

RECORDS = {"alpha": "R1a2b3c4d5e6f", "beta": "R9z8y7x6w5v4u"}


def text(value: Any) -> list[dict[str, str]]:
    """MCP-style content."""
    return [{"type": "text", "text": json.dumps(value)}]


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.created: list[dict[str, Any]] = []
        self.broken: set[str] = set()

    def call_tool(self, tool: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((tool, args))
        if tool in self.broken:
            return ToolResult(ok=False, content="tool is down")
        if tool == "find_records":
            name = re.search(r"name = '(.*)'", args["filter"])
            record_id = RECORDS.get(name.group(1)) if name else None
            rows = [{"id": record_id, "name": name.group(1)}] if record_id and name else []
            return ToolResult(ok=True, content=text({"count": len(rows), "rows": rows}))
        if tool == "create_record":
            self.created.append(args)
            return ToolResult(ok=True, content=text({"id": f"N0000000000{len(self.created)}x", "created": True}))
        if tool == "search":
            return ToolResult(ok=True, content=text({"rows": [{"id": RECORDS["alpha"]}]}))
        return ToolResult(ok=False, content=f"unknown tool {tool}")

    async def call_tool_async(self, tool: str, args: dict[str, Any]) -> ToolResult:
        return self.call_tool(tool, args)


def classify(system: str, user: str) -> str:
    """Pretends to be a model: "Create a note '<title>' for <name>"."""
    match = re.match(r"Create a note '(.*)' for (\w+)", user)
    if not match:
        return json.dumps({"intent": "small_talk", "parameters": {}})
    return json.dumps({"intent": "create_note_for_record", "parameters": {"title": match[1], "name": match[2]}})


class FakeAgent:
    """Does what a model would: find the record, then create the note."""

    def __init__(self) -> None:
        self.runs = 0

    async def __call__(self, call_tool: Any, task: Any) -> str:
        self.runs += 1
        name, title = task.parameters["name"], task.parameters["title"]
        # A typo first: the agent corrects itself, the failed step must not be learned
        await _maybe(call_tool("find_recrods", {"filter": "oops"}))
        found = await _maybe(call_tool("find_records", {"filter": f"name = '{name}'"}))
        row = json.loads(found.content[0]["text"])["rows"][0]
        await _maybe(call_tool("create_record", {"kind": "note", "parent_id": row["id"], "title": title}))
        return f"Created '{title}' for {name}"


async def _maybe(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


@pytest.fixture
def agent() -> FakeAgent:
    return FakeAgent()
