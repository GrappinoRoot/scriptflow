import asyncio
from types import SimpleNamespace

import pytest

from procedural_memory import (
    Skill,
    SkillParameterError,
    SkillStep,
    ToolResult,
    get_at_path,
    parse_tool_content,
    render_args,
    run_skill,
)


def test_exact_placeholder_keeps_the_type():
    assert render_args({"n": "{{n}}", "flag": "{{ f }}"}, {"n": 42, "f": False}) == {"n": 42, "flag": False}


def test_embedded_placeholder_is_escaped():
    assert render_args("Name = '{{name}}'", {"name": "O'Brien"}) == "Name = 'O\\'Brien'"


def test_embedded_values_use_json_spelling():
    assert render_args("a={{a}} b={{b}} c={{c}}", {"a": True, "b": 5.0, "c": None}) == "a=true b=5 c=null"


def test_step_references():
    results = [{"records": [{"Id": "X1", "Score": 9.5}]}]
    template = {
        "id": {"$from": {"step": 0, "path": "records.0.Id"}},
        "q": "Id = '{{@0.records.0.Id}}'",
        "s": "{{@0.records.0.Score}}",
    }
    assert render_args(template, {}, results) == {"id": "X1", "q": "Id = 'X1'", "s": 9.5}


def test_reference_to_a_null_value_is_not_an_error():
    assert render_args({"$from": {"step": 0, "path": "a"}}, {}, [{"a": None}]) is None


@pytest.mark.parametrize(
    "template, message",
    [
        ("{{missing}}", "Missing parameter"),
        ({"$from": {"step": 3, "path": "x"}}, "step 3"),
        ("{{@0.nope}}", 'Path "nope"'),
        ("{{@0.records.5}}", "records.5"),
    ],
)
def test_unresolvable_placeholders_raise(template, message):
    with pytest.raises(SkillParameterError, match=message):
        render_args(template, {}, [{"records": []}])


def test_custom_escape():
    assert render_args("x {{v}}", {"v": 'a"b'}, escape=lambda v: str(v).replace('"', '""')) == 'x a""b'


def test_parse_tool_content():
    assert parse_tool_content([{"type": "text", "text": '{"a": 1}'}]) == {"a": 1}
    assert parse_tool_content([SimpleNamespace(type="text", text="[1, 2]")]) == [1, 2]
    assert parse_tool_content("not json") == "not json"
    assert parse_tool_content({"already": "structured"}) == {"already": "structured"}
    assert parse_tool_content([1, 2]) == [1, 2]
    assert parse_tool_content(None) is None


def test_get_at_path():
    value = {"a": [{"b": 1}], "n": None}
    assert get_at_path(value, "a.0.b") == 1
    assert get_at_path(value, "a.-1.b", default="none") == "none"
    assert get_at_path(value, "") is value
    assert get_at_path(value, "n", default="x") is None


def _skill():
    return Skill(
        intent="demo",
        parameters=["name"],
        steps=[
            SkillStep("find", {"q": "{{name}}"}),
            SkillStep("use", {"id": {"$from": {"step": 0, "path": "id"}}}),
        ],
    )


def test_run_skill_chains_results():
    calls = []

    def call_tool(tool, args):
        calls.append((tool, args))
        return {"ok": True, "content": '{"id": "X9"}'}

    result = asyncio.run(run_skill(_skill(), {"name": "alpha"}, call_tool))
    assert result.ok
    assert calls == [("find", {"q": "alpha"}), ("use", {"id": "X9"})]
    assert result.output == '{"id": "X9"}'


def test_run_skill_never_raises():
    def failing(tool, args):
        return ToolResult(ok=False, content="down")

    def raising(tool, args):
        raise RuntimeError("boom")

    def bad_result(tool, args):
        return {"content": "{}"}  # no "ok": a failure, a step that didn't produce "id"

    assert asyncio.run(run_skill(_skill(), {}, failing)).error == "missing parameters: name"
    down = asyncio.run(run_skill(_skill(), {"name": "a"}, failing))
    assert (down.ok, down.failed_step) == (False, "find")
    assert "boom" in asyncio.run(run_skill(_skill(), {"name": "a"}, raising)).error
    assert not asyncio.run(run_skill(_skill(), {"name": "a"}, bad_result)).ok
