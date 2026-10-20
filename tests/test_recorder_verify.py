from procedural_memory import Recorder, VerifyContext, implies_mutation, is_successful_run, mutation_verifier
from procedural_memory.types import RecordedStep


def test_success_rules():
    recorder = Recorder("hi")
    assert "no tool" in is_successful_run(recorder.trace()).reason
    recorder.record_tool_call("a", {}, False)
    assert "no tool succeeded" in is_successful_run(recorder.trace()).reason
    recorder.record_tool_call("b", {}, True)
    assert "no final answer" in is_successful_run(recorder.trace()).reason
    recorder.record_final_answer("  ok  ")
    assert is_successful_run(recorder.trace()).ok
    recorder.record_skipped("c", "denied by the user")
    assert "denied by the user" in is_successful_run(recorder.trace()).reason


def test_recorded_args_are_copied():
    recorder = Recorder("hi")
    args = {"nested": {"x": 1}}
    recorder.record_tool_call("a", args, True)
    args["nested"]["x"] = 2
    assert recorder.trace().steps[0].args == {"nested": {"x": 1}}


def test_implies_mutation():
    assert implies_mutation("create_contact")
    assert implies_mutation("delete")
    assert not implies_mutation("find_contact")
    assert not implies_mutation("settings_overview")  # "set" must be a whole verb


def test_mutation_verifier():
    verify = mutation_verifier(lambda tool, args: tool == "rest" and args.get("method") == "POST")
    read = [RecordedStep("rest", {"method": "GET"}, True)]
    write = [*read, RecordedStep("rest", {"method": "POST"}, True)]
    assert verify(VerifyContext("find_contact", read, None)).ok
    assert not verify(VerifyContext("create_contact", read, None)).ok
    assert verify(VerifyContext("create_contact", write, None)).ok
