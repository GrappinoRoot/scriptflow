"""
Runnable end-to-end example with a fake model and fake tools: no API key needed.

    python examples/quickstart.py

The first request goes through the "agent", which is learned as a skill; the second one,
with different values, is replayed by the skill without calling the agent.
"""

import asyncio
import json
import re
import tempfile

from procedural_memory import ProceduralMemory, ToolResult, mutation_verifier

RECORDS = {"alpha": "R1a2b3c4d5e6f", "beta": "R9z8y7x6w5v4u"}


# --- Your model: (system, user) -> JSON text. Here a regex pretends to be one. ---------
def classify(system: str, user: str) -> str:
    match = re.match(r"Create a note '(.*)' for (\w+)", user)
    parameters = {"title": match[1], "name": match[2]} if match else {}
    return json.dumps({"intent": "create_note_for_record" if match else "other", "parameters": parameters})


# --- Your tools: whatever executor you already have. ------------------------------------
async def call_tool(tool: str, args: dict) -> ToolResult:
    print(f"    tool  {tool}({json.dumps(args)})")
    if tool == "find_records":
        name = re.search(r"name = '(.*)'", args["filter"])[1]
        rows = [{"id": RECORDS[name], "name": name}] if name in RECORDS else []
        return ToolResult(ok=True, content=[{"type": "text", "text": json.dumps({"rows": rows})}])
    if tool == "create_record":
        return ToolResult(ok=True, content=[{"type": "text", "text": '{"created": true}'}])
    return ToolResult(ok=False, content=f"unknown tool {tool}")


# --- Your agent loop: it only needs to use the call_tool it receives. -------------------
async def agent(call_tool, task) -> str:
    print("    (agent is reasoning...)")
    name, title = task.parameters["name"], task.parameters["title"]
    found = await call_tool("find_records", {"filter": f"name = '{name}'"})
    record_id = json.loads(found.content[0]["text"])["rows"][0]["id"]
    await call_tool("create_record", {"kind": "note", "parent_id": record_id, "title": title})
    return f"Created note '{title}' for {name}"


async def main() -> None:
    with tempfile.TemporaryDirectory() as root:
        memory = ProceduralMemory(
            root=root,
            classify=classify,
            verify=mutation_verifier(lambda tool, args: tool == "create_record"),
        )
        for request in ["Create a note 'Follow up' for alpha", "Create a note 'Check status' for beta"]:
            print(f"\n> {request}")
            result = await memory.handle(request, call_tool=call_tool, agent=agent)
            print(f"  source={result.source} ok={result.ok}")
            if result.learned:
                print(f"  learned: {result.learned.saved.intent if result.learned.saved else result.learned.reason}")

        print("\nLearned skill:")
        print(json.dumps(memory.store.get("create_note_for_record").to_dict(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
