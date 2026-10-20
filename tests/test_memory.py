import asyncio

import pytest
from conftest import classify

from procedural_memory import MemoryStore, ProceduralMemory, Verdict, mutation_verifier

INTENT = "create_note_for_record"


def memory(**options):
    return ProceduralMemory(store=MemoryStore(), classify=classify, **options)


def handle(mem, message, backend, agent, use_async=False):
    call_tool = backend.call_tool_async if use_async else backend.call_tool
    return asyncio.run(mem.handle(message, call_tool=call_tool, agent=agent))


@pytest.mark.parametrize("use_async", [False, True])
def test_learns_then_replays(backend, agent, use_async):
    mem = memory()
    first = handle(mem, "Create a note 'Follow up' for alpha", backend, agent, use_async)
    assert (first.source, first.ok) == ("agent", True)
    assert first.learned.saved is not None, first.learned.reason
    assert first.output == "Created 'Follow up' for alpha"

    backend.calls.clear()
    second = handle(mem, "Create a note 'Check status' for beta", backend, agent, use_async)
    assert (second.source, second.ok) == ("skill", True)
    assert agent.runs == 1  # the model did not reason again
    assert backend.calls == [
        ("find_records", {"filter": "name = 'beta'"}),
        ("create_record", {"kind": "note", "parent_id": "R9z8y7x6w5v4u", "title": "Check status"}),
    ]
    assert mem.store.get(INTENT).stats.runs == 1


def test_handle_sync_with_file_store(tmp_path, backend, agent):
    mem = ProceduralMemory(root=tmp_path, classify=classify)
    assert mem.handle_sync("Create a note 'A' for alpha", call_tool=backend.call_tool, agent=agent).source == "agent"
    assert mem.handle_sync("Create a note 'B' for alpha", call_tool=backend.call_tool, agent=agent).source == "skill"
    assert (tmp_path / f"{INTENT}.json").exists()


def test_failed_skill_falls_back_and_is_repaired(backend, agent):
    mem = memory()
    handle(mem, "Create a note 'A' for alpha", backend, agent)
    backend.broken.add("create_record")
    result = handle(mem, "Create a note 'B' for alpha", backend, agent)
    assert result.source == "agent" and agent.runs == 2
    assert result.run is not None and not result.run.ok
    assert result.learned.saved is None  # the agent's run failed too: nothing to learn from the broken tool
    assert mem.store.get(INTENT).stats.failures == 1


def test_a_working_skill_is_not_replaced_by_a_different_procedure(backend, agent):
    mem = memory()
    handle(mem, "Create a note 'A' for alpha", backend, agent)
    backend.broken.add("find_records")

    async def other_agent(call_tool, task):
        call_tool("search", {"term": task.parameters["name"]})
        call_tool("create_record", {"parent_id": "R1a2b3c4d5e6f", "title": task.parameters["title"]})
        return "done differently"

    result = asyncio.run(mem.handle("Create a note 'B' for alpha", call_tool=backend.call_tool, agent=other_agent))
    assert result.learned.saved is None
    assert "different tools" in result.learned.reason
    assert mem.store.get(INTENT).tools == ["find_records", "create_record"]


def test_verify_refuses_and_fails_closed(backend, agent):
    refuse = memory(verify=mutation_verifier(lambda tool, args: False))
    assert "no mutating tool ran" in handle(refuse, "Create a note 'A' for alpha", backend, agent).learned.reason

    def broken(context):
        raise RuntimeError("bug in verifier")

    assert (
        "verify failed" in handle(memory(verify=broken), "Create a note 'A' for alpha", backend, agent).learned.reason
    )
    accepted = memory(verify=lambda context: Verdict(True))
    assert handle(accepted, "Create a note 'A' for alpha", backend, agent).learned.saved is not None


def test_skipped_step_prevents_learning(backend):
    async def cautious_agent(call_tool, task):
        task.record_skipped("delete_everything", "denied by the user")
        call_tool("find_records", {"filter": "name = 'alpha'"})
        return "stopped"

    result = asyncio.run(
        memory().handle("Create a note 'A' for alpha", call_tool=backend.call_tool, agent=cautious_agent)
    )
    assert "denied by the user" in result.learned.reason


def test_instrument_records_exceptions_and_reraises():
    mem = memory()
    task = asyncio.run(mem.resolve("anything"))

    def explode(tool, args):
        raise TimeoutError("slow")

    with pytest.raises(TimeoutError):
        mem.instrument(task, explode)("find_records", {"filter": 1})
    step = task.recorder.trace().steps[0]
    assert (step.tool, step.ok, step.content) == ("find_records", False, "slow")


def test_without_agent_or_classifier(backend):
    no_agent = asyncio.run(memory().handle("Create a note 'A' for alpha", call_tool=backend.call_tool))
    assert (no_agent.source, no_agent.ok, no_agent.learned.reason) == ("agent", False, "no agent provided")

    plain = ProceduralMemory(store=MemoryStore())
    task = asyncio.run(plain.resolve("Create a note 'A' for alpha"))
    assert task.intent is None and task.skill is None
    assert plain.learn(task).reason == "no intent was extracted"


def test_store_errors_never_break_the_agent(backend, agent):
    class BrokenStore(MemoryStore):
        def all(self):
            raise OSError("disk gone")

        def get(self, intent):
            raise OSError("disk gone")

    result = asyncio.run(
        ProceduralMemory(store=BrokenStore(), classify=classify).handle(
            "Create a note 'A' for alpha", call_tool=backend.call_tool, agent=agent
        )
    )
    assert result.source == "agent" and result.ok
